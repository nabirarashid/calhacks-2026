import type { EventType } from '@shared/contracts';
import type { DashboardEvent } from './events';

export type SourceStatus = 'connecting' | 'live' | 'reconnecting' | 'replay' | 'complete' | 'error';

export interface EventObserver {
  next(event: DashboardEvent): void;
  error?(error: Error): void;
  status?(status: SourceStatus): void;
  complete?(): void;
}

export interface EventSource {
  subscribe(observer: EventObserver | ((event: DashboardEvent) => void)): () => void;
}

export interface WebSocketSourceOptions {
  url?: string;
  reconnectDelayMs?: number;
  maxReconnectDelayMs?: number;
  webSocketFactory?: (url: string) => WebSocket;
}

const EVENT_TYPES: ReadonlySet<EventType | 'analysis_progress'> = new Set([
  'run_started',
  'design_evaluated',
  'generation_complete',
  'champion_updated',
  'geometry_ready',
  'agent_message',
  'baseline_progress',
  'landscape_ready',
  'budget_update',
  'analysis_progress',
  'run_complete',
  'error',
]);

function asObserver(
  observer: EventObserver | ((event: DashboardEvent) => void),
): EventObserver {
  return typeof observer === 'function' ? { next: observer } : observer;
}

function asError(error: unknown, prefix?: string): Error {
  const value = error instanceof Error ? error : new Error(String(error));
  return prefix ? new Error(`${prefix}: ${value.message}`) : value;
}

/** Minimal runtime validation at the untrusted socket/file boundary. */
export function parseEvent(value: unknown): DashboardEvent {
  if (typeof value !== 'object' || value === null) throw new Error('event must be an object');
  const candidate = value as Record<string, unknown>;
  if (candidate.v !== 1) throw new Error('event.v must be 1');
  if (typeof candidate.type !== 'string' || !EVENT_TYPES.has(candidate.type as EventType | 'analysis_progress')) {
    throw new Error(`unknown event type: ${String(candidate.type)}`);
  }
  if (typeof candidate.run_id !== 'string' || candidate.run_id.length === 0) {
    throw new Error('event.run_id must be a non-empty string');
  }
  if (!Number.isSafeInteger(candidate.seq) || (candidate.seq as number) < 0) {
    throw new Error('event.seq must be a non-negative safe integer');
  }
  if (typeof candidate.ts !== 'number' || !Number.isFinite(candidate.ts)) {
    throw new Error('event.ts must be finite');
  }
  if (typeof candidate.payload !== 'object' || candidate.payload === null) {
    throw new Error('event.payload must be an object');
  }
  return candidate as unknown as DashboardEvent;
}

export function parseJsonl(jsonl: string): DashboardEvent[] {
  const events: DashboardEvent[] = [];
  for (const [index, rawLine] of jsonl.split(/\r?\n/).entries()) {
    const line = rawLine.trim();
    if (!line) continue;
    try {
      events.push(parseEvent(JSON.parse(line)));
    } catch (error) {
      throw asError(error, `Invalid JSONL on line ${index + 1}`);
    }
  }
  return events;
}

export const parseJSONL = parseJsonl;

function defaultWebSocketUrl(runId: string): string {
  if (typeof window === 'undefined') {
    throw new Error('wsSource requires an explicit url outside a browser');
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = new URL('/ws', `${protocol}//${window.location.host}`);
  url.searchParams.set('run_id', runId);
  return url.toString();
}

export function wsSource(runId: string, options: WebSocketSourceOptions = {}): EventSource {
  const initialDelay = Math.max(0, options.reconnectDelayMs ?? 500);
  const maximumDelay = Math.max(initialDelay, options.maxReconnectDelayMs ?? 8_000);

  return {
    subscribe(rawObserver) {
      const observer = asObserver(rawObserver);
      let cancelled = false;
      let socket: WebSocket | null = null;
      let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
      let reconnectAttempts = 0;
      const seenSeqByRun = new Map<string, Set<number>>();

      const url = options.url ?? defaultWebSocketUrl(runId);
      const factory = options.webSocketFactory ?? ((target: string) => new WebSocket(target));

      const reportError = (error: unknown) => observer.error?.(asError(error));

      const connect = () => {
        if (cancelled) return;
        observer.status?.(reconnectAttempts === 0 ? 'connecting' : 'reconnecting');
        try {
          socket = factory(url);
        } catch (error) {
          reportError(error);
          scheduleReconnect();
          return;
        }

        socket.addEventListener('open', () => {
          if (cancelled) return;
          reconnectAttempts = 0;
          observer.status?.('live');
        });
        socket.addEventListener('message', (message) => {
          if (cancelled) return;
          try {
            const raw = typeof message.data === 'string' ? message.data : String(message.data);
            const event = parseEvent(JSON.parse(raw));
            const seen = seenSeqByRun.get(event.run_id) ?? new Set<number>();
            if (seen.has(event.seq)) return;
            seen.add(event.seq);
            seenSeqByRun.set(event.run_id, seen);
            observer.next(event);
          } catch (error) {
            reportError(asError(error, 'Invalid websocket event'));
          }
        });
        socket.addEventListener('error', () => {
          if (!cancelled) reportError(new Error('WebSocket connection error'));
        });
        socket.addEventListener('close', () => {
          socket = null;
          if (!cancelled) scheduleReconnect();
        });
      };

      const scheduleReconnect = () => {
        if (cancelled || reconnectTimer !== null) return;
        observer.status?.('reconnecting');
        const delay = Math.min(maximumDelay, initialDelay * 2 ** reconnectAttempts);
        reconnectAttempts += 1;
        reconnectTimer = setTimeout(() => {
          reconnectTimer = null;
          connect();
        }, delay);
      };

      connect();

      return () => {
        if (cancelled) return;
        cancelled = true;
        if (reconnectTimer !== null) clearTimeout(reconnectTimer);
        reconnectTimer = null;
        if (socket && socket.readyState < 2) socket.close(1000, 'subscription cancelled');
        socket = null;
      };
    },
  };
}

export function fileSource(jsonl: string, speed = 1): EventSource {
  if (!Number.isFinite(speed) || speed <= 0) throw new Error('Replay speed must be greater than zero');
  const events = parseJsonl(jsonl);

  return {
    subscribe(rawObserver) {
      const observer = asObserver(rawObserver);
      let cancelled = false;
      let timer: ReturnType<typeof setTimeout> | null = null;
      let index = 0;

      observer.status?.('replay');

      const emitNext = () => {
        if (cancelled) return;
        if (index >= events.length) {
          observer.status?.('complete');
          observer.complete?.();
          return;
        }

        observer.next(events[index]);
        const current = events[index];
        index += 1;
        if (index >= events.length) {
          timer = setTimeout(emitNext, 0);
          return;
        }

        const gapMs = Math.max(0, (events[index].ts - current.ts) * 1_000 / speed);
        timer = setTimeout(emitNext, gapMs);
      };

      timer = setTimeout(emitNext, 0);
      return () => {
        cancelled = true;
        if (timer !== null) clearTimeout(timer);
        timer = null;
      };
    },
  };
}
