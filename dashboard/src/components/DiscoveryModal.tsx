import type { DesignSpace } from '@shared/contracts';
import { useState } from 'react';

interface DiscoveryModalProps {
  onClose: () => void;
  onDiscover: (url: string, probe: boolean) => Promise<DesignSpace>;
  onUse: (space: DesignSpace) => void;
}

export function DiscoveryModal({ onClose, onDiscover, onUse }: DiscoveryModalProps) {
  const [url, setUrl] = useState('');
  const [probe, setProbe] = useState(false);
  const [space, setSpace] = useState<DesignSpace | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const discover = async () => {
    setBusy(true);
    setError(null);
    try {
      setSpace(await onDiscover(url, probe));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const patchParam = (index: number, field: 'min' | 'max', value: number) => {
    if (!space) return;
    const parameters = [...space.parameters];
    parameters[index] = { ...parameters[index], [field]: value };
    setSpace({ ...space, parameters });
  };

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Discover an Onshape design space">
      <div className="modal-card max-w-4xl">
        <button className="modal-close" onClick={onClose} type="button">×</button>
        <div className="eyebrow text-cyan">Tier 3 · Any Part Studio</div>
        <h2 className="mt-2 text-2xl font-semibold text-white">Discover a design space</h2>
        <p className="mt-1 text-sm text-slate-400">Paste an Onshape Part Studio URL. Darwin reads configuration inputs and proposes safe bounds.</p>
        <div className="mt-5 flex flex-wrap gap-2">
          <input className="min-w-[280px] flex-1 rounded-xl border border-line bg-ink px-3 py-2 text-sm outline-none focus:border-cyan/60" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://cad.onshape.com/documents/…" />
          <label className="flex items-center gap-2 rounded-xl border border-line px-3 text-xs text-slate-400"><input type="checkbox" checked={probe} onChange={(event) => setProbe(event.target.checked)} /> Probe corners (≤6 calls)</label>
          <button className="control-button primary" disabled={!url.trim() || busy} onClick={() => void discover()}>{busy ? 'Discovering…' : 'Discover'}</button>
        </div>
        {error ? <p className="mt-3 rounded-lg border border-coral/30 bg-coral/5 p-2 text-xs text-coral">{error}</p> : null}
        {space ? (
          <div className="mt-5">
            <div className="flex items-center justify-between">
              <div><h3 className="font-semibold text-slate-100">{space.name}</h3><p className="font-mono text-[10px] text-slate-500">{space.parameters.length} parameters · {space.source.mode}</p></div>
              <label className="text-xs text-slate-400">Scorer <select className="ml-2 rounded-md border border-line bg-ink px-2 py-1" value={space.scorer || 'fin_v1'} onChange={(event) => setSpace({ ...space, scorer: event.target.value })}><option value="fin_v1">fin_v1 physics</option></select></label>
            </div>
            <div className="mt-3 max-h-72 overflow-auto rounded-xl border border-line">
              <table className="w-full text-left text-xs"><thead className="sticky top-0 bg-panel font-mono text-[9px] uppercase text-slate-500"><tr><th className="p-2">Parameter</th><th>Kind</th><th>Min</th><th>Max</th><th>Default</th></tr></thead><tbody>
                {space.parameters.map((parameter, index) => <tr className="border-t border-line" key={parameter.name}><td className="p-2 font-mono text-cyan">{parameter.name}</td><td className="text-slate-500">{parameter.kind}</td><td>{parameter.kind !== 'choice' ? <input className="bound-input" type="number" value={parameter.min ?? 0} onChange={(event) => patchParam(index, 'min', Number(event.target.value))} /> : '—'}</td><td>{parameter.kind !== 'choice' ? <input className="bound-input" type="number" value={parameter.max ?? 0} onChange={(event) => patchParam(index, 'max', Number(event.target.value))} /> : '—'}</td><td className="font-mono text-slate-300">{String(parameter.default)}</td></tr>)}
              </tbody></table>
            </div>
            <div className="mt-4 flex justify-end"><button className="control-button primary" onClick={() => onUse({ ...space, scorer: space.scorer || 'fin_v1' })}>Use in optimizer</button></div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
