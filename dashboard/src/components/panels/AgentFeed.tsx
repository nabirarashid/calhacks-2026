import type { AgentMessage, AgentRole, ErrorPayload } from '@shared/contracts';
import { AGENT_COLORS, EmptyPanel, PANEL_COLORS, PanelFrame, formatCompact, shortDesignId } from './panelPrimitives';

export type AgentFeedItem =
  | { type: 'message'; message: AgentMessage; seq?: number; ts?: number }
  | { type: 'error'; error: ErrorPayload; seq?: number; ts?: number; id?: string };

export interface AgentFeedProps {
  items?: AgentFeedItem[];
  messages?: AgentMessage[];
  errors?: ErrorPayload[];
  highlightedRef?: string | null;
  onReferenceClick?: (designId: string, message?: AgentMessage) => void;
  maxHeight?: number | string;
  className?: string;
}

const agentLabels: Record<AgentRole, string> = {
  goal_parser: 'Goal parser',
  proposer: 'Proposer',
  critic: 'Critic',
  strategist: 'Strategist',
  reporter: 'Reporter',
  system: 'System',
};

const agentGlyphs: Record<AgentRole, string> = {
  goal_parser: 'G',
  proposer: 'P',
  critic: 'C',
  strategist: 'S',
  reporter: 'R',
  system: '!',
};

function isFallbackModel(model: string): boolean {
  return !model || /mock|fallback|rules|replay|none/i.test(model);
}

function MessageCard({
  message,
  highlightedRef,
  onReferenceClick,
}: {
  message: AgentMessage;
  highlightedRef?: string | null;
  onReferenceClick?: AgentFeedProps['onReferenceClick'];
}) {
  const role = message.agent in AGENT_COLORS ? message.agent : 'system';
  const color = AGENT_COLORS[role];
  const warning = message.kind === 'warning';
  const fallback = isFallbackModel(message.model);
  const metadata = [
    message.model || 'unknown model',
    `${formatCompact(message.latency_ms, 0)} ms`,
    `$${formatCompact(message.cost_usd, 4)}`,
    `${formatCompact(message.tokens_in + message.tokens_out, 0)} tok`,
  ].join(' · ');

  return (
    <article
      className={`group rounded-xl border p-3 transition-colors ${warning ? 'border-amber/35 bg-amber/[0.06]' : 'border-line bg-ink/35 hover:border-slate-600'}`}
      title={metadata}
    >
      <div className="flex items-start gap-2.5">
        <div
          className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border font-mono text-[11px] font-bold"
          style={{ color, borderColor: `${color}55`, background: `${color}12` }}
          aria-hidden="true"
        >
          {agentGlyphs[role]}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-xs font-semibold" style={{ color }}>{agentLabels[role]}</span>
            <span className="font-mono text-[9px] uppercase tracking-wider text-slate-600">{message.kind}</span>
            {fallback ? (
              <span className="rounded border border-slate-700 px-1.5 py-0.5 font-mono text-[8px] uppercase text-slate-500">
                {/rules/i.test(message.model) ? 'rules' : 'fallback'}
              </span>
            ) : null}
            {typeof message.generation === 'number' ? (
              <span className="ml-auto font-mono text-[9px] text-slate-600">G{message.generation}</span>
            ) : null}
          </div>
          <p className={`mt-1 text-xs leading-relaxed ${warning ? 'text-amber' : 'text-slate-300'}`}>
            {message.summary || 'Agent update'}
          </p>
          {message.body ? (
            <details className="mt-2 text-[11px] leading-relaxed text-slate-500">
              <summary className="cursor-pointer select-none text-slate-500 hover:text-slate-300">Details</summary>
              <p className="mt-1.5 whitespace-pre-wrap border-l border-line pl-2.5">{message.body}</p>
            </details>
          ) : null}
          {message.refs?.length ? (
            <div className="mt-2 flex flex-wrap gap-1">
              {message.refs.map((ref) => (
                <button
                  key={ref}
                  type="button"
                  onClick={() => onReferenceClick?.(ref, message)}
                  className={`rounded-md border px-1.5 py-0.5 font-mono text-[9px] transition-colors ${
                    highlightedRef === ref
                      ? 'border-mint bg-mint/10 text-mint'
                      : 'border-line text-cyan hover:border-cyan/50 hover:bg-cyan/5'
                  }`}
                >
                  ↗ {shortDesignId(ref)}
                </button>
              ))}
            </div>
          ) : null}
          <div className="mt-2 hidden font-mono text-[9px] text-slate-600 group-hover:block">{metadata}</div>
        </div>
      </div>
    </article>
  );
}

function ErrorCard({ error }: { error: ErrorPayload }) {
  return (
    <article className="rounded-xl border border-amber/40 bg-amber/[0.07] p-3" role="status">
      <div className="flex items-center gap-2 font-mono text-[9px] uppercase tracking-wider text-amber">
        <span className="flex h-5 w-5 items-center justify-center rounded-full border border-amber/50">!</span>
        {error.component} · {error.code}
        <span className="ml-auto">{error.recoverable ? 'degraded' : 'attention'}</span>
      </div>
      <p className="mt-2 text-xs leading-relaxed text-amber/90">{error.message || 'An unknown system error occurred.'}</p>
      {error.degraded_to ? <p className="mt-1 font-mono text-[9px] text-slate-500">Continuing with {error.degraded_to}</p> : null}
    </article>
  );
}

export function AgentFeed({
  items,
  messages = [],
  errors = [],
  highlightedRef,
  onReferenceClick,
  maxHeight = 560,
  className,
}: AgentFeedProps) {
  const feedItems: AgentFeedItem[] = items ?? [
    ...messages.map((message) => ({ type: 'message' as const, message })),
    ...errors.map((error, index) => ({ type: 'error' as const, error, id: `error-${index}` })),
  ];

  return (
    <PanelFrame
      title="Agent feed"
      eyebrow={feedItems.length ? `${feedItems.length} transmissions` : 'Live reasoning'}
      action={<span className="inline-flex items-center gap-1.5 font-mono text-[9px] uppercase text-slate-500"><i className="h-1.5 w-1.5 animate-pulse rounded-full bg-mint" />stream</span>}
      className={className}
    >
      {feedItems.length === 0 ? (
        <EmptyPanel label="Agents are standing by" detail="Proposals, critiques, strategy, and system degradations appear here." />
      ) : (
        <div className="space-y-2 overflow-y-auto p-3 scrollbar-thin" style={{ maxHeight }} aria-live="polite">
          {feedItems.map((item, index) =>
            item.type === 'message' ? (
              <MessageCard
                key={item.message.message_id || `message-${index}`}
                message={item.message}
                highlightedRef={highlightedRef}
                onReferenceClick={onReferenceClick}
              />
            ) : (
              <ErrorCard key={item.id ?? `error-${item.seq ?? index}`} error={item.error} />
            ),
          )}
        </div>
      )}
    </PanelFrame>
  );
}

export { AGENT_COLORS } from './panelPrimitives';
