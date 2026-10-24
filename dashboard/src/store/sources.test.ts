import type { AnyDarwinEvent } from '@shared/contracts';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { fileSource, parseJsonl, wsSource } from './sources';

function event(seq: number, ts: number): AnyDarwinEvent {
  return {
    v: 1,
    type: 'error',
    run_id: 'run_source',
    seq,
    ts,
    payload: {
      component: 'backend',
      code: 'test',
      message: `event ${seq}`,
      recoverable: true,
    },
  };
}

class FakeSocket {
  readyState = 0;
  private listeners = new Map<string, Array<(value: any) => void>>();

  addEventListener(type: string, listener: (value: any) => void) {
    const listeners = this.listeners.get(type) ?? [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  emit(type: string, value: any = {}) {
    for (const listener of this.listeners.get(type) ?? []) listener(value);
  }

  close = vi.fn(() => {
    this.readyState = 3;
  });
}

describe('event sources', () => {
  afterEach(() => vi.useRealTimers());

  it('parses JSONL with blank lines and reports the bad line', () => {
    expect(parseJsonl(`${JSON.stringify(event(1, 1))}\n\n`)).toEqual([event(1, 1)]);
    expect(() => parseJsonl(`${JSON.stringify(event(1, 1))}\n{nope}`)).toThrow(
      'Invalid JSONL on line 2',
    );
  });

  it('accepts the additive analysis_progress event used by structural solvers', () => {
    const progress = {
      v: 1,
      type: 'analysis_progress',
      run_id: 'run_source',
      seq: 4,
      ts: 2,
      payload: { design_id: 'd1', adapter_id: 'structural_fea_v1', stage: 'mesh', pct: 45, elapsed_ms: 120 },
    };
    expect(parseJsonl(JSON.stringify(progress))).toEqual([progress]);
  });

  it('replays timestamp gaps at the requested speed and can be cancelled', () => {
    vi.useFakeTimers();
    const lines = [event(1, 10), event(2, 10.4), event(3, 11)]
      .map((value) => JSON.stringify(value))
      .join('\n');
    const received: number[] = [];
    const complete = vi.fn();
    const cancel = fileSource(lines, 2).subscribe({
      next: (value) => received.push(value.seq),
      complete,
    });

    vi.advanceTimersByTime(0);
    expect(received).toEqual([1]);
    vi.advanceTimersByTime(199);
    expect(received).toEqual([1]);
    vi.advanceTimersByTime(1);
    expect(received).toEqual([1, 2]);
    cancel();
    vi.runAllTimers();
    expect(received).toEqual([1, 2]);
    expect(complete).not.toHaveBeenCalled();
  });

  it('reconnects a websocket and cancellation prevents another reconnect', () => {
    vi.useFakeTimers();
    const sockets: FakeSocket[] = [];
    const received: number[] = [];
    const statuses: string[] = [];
    const source = wsSource('run_source', {
      url: 'ws://example.test/ws?run_id=run_source',
      reconnectDelayMs: 100,
      webSocketFactory: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket as unknown as WebSocket;
      },
    });
    const cancel = source.subscribe({
      next: (value) => received.push(value.seq),
      status: (value) => statuses.push(value),
    });

    expect(sockets).toHaveLength(1);
    sockets[0].readyState = 1;
    sockets[0].emit('open');
    sockets[0].emit('message', { data: JSON.stringify(event(1, 1)) });
    sockets[0].emit('message', { data: JSON.stringify(event(1, 1)) });
    expect(received).toEqual([1]);
    sockets[0].emit('close');
    vi.advanceTimersByTime(100);
    expect(sockets).toHaveLength(2);
    expect(statuses).toContain('reconnecting');

    sockets[1].emit('message', { data: JSON.stringify(event(1, 1)) });
    sockets[1].emit('message', { data: JSON.stringify(event(2, 2)) });
    expect(received).toEqual([1, 2]);

    sockets[1].readyState = 1;
    cancel();
    expect(sockets[1].close).toHaveBeenCalled();
    vi.runAllTimers();
    expect(sockets).toHaveLength(2);
  });
});
