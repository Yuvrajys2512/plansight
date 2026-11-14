import { useEffect, useRef, useState } from 'react';
import QRCode from 'qrcode';

// <model-viewer> (Google) ships its own three.js; load its self-contained build only on the AR page.
const MV_SRC = 'https://cdn.jsdelivr.net/npm/@google/model-viewer@4.0.0/dist/model-viewer.min.js';
function useModelViewer() {
  const [ready, setReady] = useState(!!customElements.get('model-viewer'));
  useEffect(() => {
    if (ready) return;
    const s = document.createElement('script'); s.type = 'module'; s.src = MV_SRC;
    s.onload = () => customElements.whenDefined('model-viewer').then(() => setReady(true));
    document.head.appendChild(s);
  }, [ready]);
  return ready;
}

declare module 'react' {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace JSX { interface IntrinsicElements { 'model-viewer': React.DetailedHTMLProps<React.HTMLAttributes<HTMLElement>, HTMLElement> & Record<string, unknown> } }
}

type Ans = { value?: unknown; unit?: string | null; evidence?: unknown[]; abstained?: boolean; reason?: string; cost_usd?: number; naive_cost_usd?: number };
const DEFAULT_QS: Record<string, string[]> = {
  cubicasa5k: ['How many doors are shown on this floor plan?', 'How many windows are shown on this floor plan?', 'How many toilets are shown on this floor plan?'],
  swiss_dwellings: ['How many doors are on this floor plan?', 'How many windows are on this floor plan?', 'How many apartments (residential units) are shown on this floor plan?'],
};

export const arUrl = (path: string, q?: string | null) => `${location.origin}/?ar=${encodeURIComponent(path)}${q ? `&q=${encodeURIComponent(q)}` : ''}`;
export const xrUrl = (path: string, q?: string | null) => `${location.origin}/?xr=${encodeURIComponent(path)}${q ? `&q=${encodeURIComponent(q)}` : ''}`;

/** Phone page: the drawing as a tabletop hologram; asking a question bakes its evidence into the model in lime. */
export function ArView({ path, initialQ }: { path: string; initialQ?: string | null }) {
  const ready = useModelViewer();
  const source = path.split('/')[1] || '';
  const [q, setQ] = useState<string | null>(initialQ || null);
  const [input, setInput] = useState('');
  const [ans, setAns] = useState<Ans | null>(null);
  const [loading, setLoading] = useState(false);
  const [examples, setExamples] = useState<string[]>([]);
  useEffect(() => { fetch(`/api/examples?path=${encodeURIComponent(path)}`).then(r => r.ok ? r.json() : { examples: [] }).then(d => setExamples([...(DEFAULT_QS[source] || []), ...(d.examples || [])].filter((v, i, a) => a.indexOf(v) === i).slice(0, 5))).catch(() => {}); }, [path, source]);
  useEffect(() => {
    if (!q) { setAns(null); return; }
    setLoading(true);
    fetch('/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path, question: q }) }).then(r => r.json()).then(setAns).catch(() => setAns({ abstained: true, reason: 'Could not reach PlanSight.' }));
  }, [q, path]);
  const mv = useRef<HTMLElement>(null);
  const src0 = `/api/ar/model.glb?path=${encodeURIComponent(path)}${q ? `&question=${encodeURIComponent(q)}` : ''}`;
  const src = src0;
  useEffect(() => { const el = mv.current; if (!el) return; const done = () => setLoading(false); el.addEventListener('load', done); el.addEventListener('error', done); const t = setTimeout(done, 15000); return () => { el.removeEventListener('load', done); el.removeEventListener('error', done); clearTimeout(t); }; }, [src, ready]);
  const n = ans?.evidence?.length ?? 0;
  return <main className="phone ar">
    <div className="phone-brand"><span className="brandmark">◎</span><b>PlanSight</b><em>AR</em><a className="live-link" href={xrUrl(path, q)}>📷 Live camera AR</a></div>
    <div className="ar-stage">
      {ready ? <model-viewer ref={mv} key={src} src={src} ar="" ar-modes="webxr scene-viewer quick-look" ar-placement="floor" ar-scale="fixed" camera-controls="" auto-rotate="" auto-rotate-delay="0" rotation-per-second="18deg" shadow-intensity="1.2" shadow-softness=".8" exposure="1.05" environment-image="neutral" camera-orbit="35deg 58deg 105%" interaction-prompt="none" style={{ width: '100%', height: '100%', background: 'transparent' }}>
        <button slot="ar-button" className="btn-primary ar-btn">🪄 Place it on your table</button>
        <div slot="progress-bar" />
      </model-viewer> : <div className="scene-msg">Loading 3D…</div>}
      {loading && <div className="ar-loading"><i className="pulse" /> building the hologram…</div>}
    </div>
    {ans && !ans.abstained ? <div className="ar-answer"><b>{String(ans.value)}</b><span>{q}<small>{n ? `${n} highlighted in lime · cost $${(ans.cost_usd ?? 0).toFixed(5)}` : 'exact answer from the drawing'}</small></span></div>
      : ans?.abstained ? <div className="ar-answer warn"><span>{ans.reason}</span></div>
      : <p className="ar-tip">Tap <b>Place it on your table</b>, point at a flat surface, then ask a question: the evidence lights up in lime on the hologram.</p>}
    <div className="ar-chips">{examples.map(e => <button key={e} className={e === q ? 'on' : ''} onClick={() => setQ(e)}>{e.replace(/ Count doorways.*$/, '').replace(' shown on this floor plan', '').replace(' on this floor plan', '')}</button>)}</div>
    <form className="ar-ask" onSubmit={e => { e.preventDefault(); if (input.trim()) setQ(input.trim()); }}><input value={input} onChange={e => setInput(e.target.value)} placeholder="Ask anything · any language" /><button className="btn-primary">Ask</button></form>
  </main>;
}

/** Laptop: QR that opens the current drawing + question as AR on the visitor's phone. */
export function ArQr({ path, q, onClose }: { path: string; q?: string | null; onClose: () => void }) {
  const [qr, setQr] = useState('');
  const url = xrUrl(path, q);
  useEffect(() => { QRCode.toDataURL(url, { margin: 1, width: 360 }).then(setQr).catch(() => {}); }, [url]);
  return <div className="snap-backdrop" onClick={onClose}><div className="snap-modal ar-modal" onClick={e => e.stopPropagation()}>
    <button className="x" onClick={onClose}>✕</button>
    <span className="kicker">Augmented reality</span>
    <h2>Put this building<br />on your table.</h2>
    <div className="snap-cols"><div className="qr">{qr && <img src={qr} alt="QR code for AR view" />}<p><b>Scan with your phone</b>, point the camera at the table, tap, and watch the building construct itself.</p></div>
      <div className="ar-explain"><p>The hologram is generated for this exact answer: {q ? <b>“{q.replace(/ Count doorways.*$/, '')}”</b> : 'the drawing'} — every counted item is lime, so you can check the evidence from any angle.</p><p>Ask another question on the phone and the hologram re-lights.</p><p className="dim">Android: live camera AR (WebXR) · the building constructs itself on the table · iPhone: Apple Quick Look fallback</p></div></div>
  </div></div>;
}
