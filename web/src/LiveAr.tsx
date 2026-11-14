import { useEffect, useRef, useState } from 'react';
import { ArEngine, type XrAnswer } from './xrEngine';
import { sfx } from './sfx';

type Ans = XrAnswer & { unit?: string | null; reason?: string; cost_usd?: number; naive_cost_usd?: number };
const DEFAULT_QS: Record<string, string[]> = {
  cubicasa5k: ['How many doors are shown on this floor plan?', 'How many windows are shown on this floor plan?', 'How many toilets are shown on this floor plan?'],
  swiss_dwellings: ['How many doors are on this floor plan?', 'How many windows are on this floor plan?', 'How many apartments (residential units) are shown on this floor plan?'],
};
const short = (q: string) => q.replace(/ Count doorways.*$/, '').replace(/ (are )?(shown )?on this floor plan/, '').replace(/ in the model '.*'/, '');

/** Full-screen camera AR: find the table, tap, the building constructs itself, ask and watch the evidence light up. */
export function LiveAr({ path, initialQ, fallbackUrl }: { path: string; initialQ?: string | null; fallbackUrl: string }) {
  const overlay = useRef<HTMLDivElement>(null);
  const engine = useRef<ArEngine | null>(null);
  const [supported, setSupported] = useState<boolean | null>(null);
  const [phase, setPhase] = useState<'intro' | 'loading' | 'scanning' | 'placed'>('intro');
  const [err, setErr] = useState('');
  const [q, setQ] = useState<string | null>(null);
  const [ans, setAns] = useState<Ans | null>(null);
  const [count, setCount] = useState<[number, number]>([0, 0]);
  const [busy, setBusy] = useState(false);
  const [surface, setSurface] = useState(false);
  const [scanSecs, setScanSecs] = useState(0);
  const [input, setInput] = useState('');
  const [examples, setExamples] = useState<string[]>([]);
  const source = path.split('/')[1] || '';

  useEffect(() => { void ArEngine.supported().then(setSupported); }, []);
  useEffect(() => { fetch(`/api/examples?path=${encodeURIComponent(path)}`).then(r => r.ok ? r.json() : { examples: [] }).then(d => setExamples([...(DEFAULT_QS[source] || []), ...(d.examples || [])].filter((v, i, a) => a.indexOf(v) === i).slice(0, 5))).catch(() => {}); }, [path, source]);

  const ask = async (question: string) => {
    if (!engine.current) return; setQ(question); setBusy(true); setAns(null); sfx.scan();
    try {
      const a: Ans = await fetch('/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path, question }) }).then(r => r.json());
      setAns(a); engine.current.highlight(a);
    } catch { setAns({ abstained: true, reason: 'Could not reach PlanSight.' }); }
    finally { setBusy(false); }
  };

  const start = async () => {
    setErr(''); setPhase('loading');
    try {
      const e = new ArEngine(); engine.current = e;
      e.onCount = (a, b) => setCount([a, b]);
      e.onTick = i => sfx.tick(i);
      e.onSurface = f => { setSurface(f); if (f) sfx.tick(8); };
      e.onDone = () => setTimeout(() => sfx.stamp(), 150);
      e.onPlaced = () => { sfx.whoosh(); setPhase('placed'); if (initialQ) setTimeout(() => void ask(initialQ), 3200); };
      e.onEnd = () => { setPhase('intro'); setAns(null); setQ(null); setCount([0, 0]); };
      await e.load(path);
      await e.start(overlay.current!);
      setPhase('scanning');
    } catch (x) { setErr(x instanceof Error ? x.message : 'Could not start AR'); setPhase('intro'); engine.current?.end(); }
  };
  useEffect(() => { if (phase !== 'scanning') { setScanSecs(0); return; } const t0 = Date.now(); const t = setInterval(() => setScanSecs(Math.floor((Date.now() - t0) / 1000)), 500); return () => clearInterval(t); }, [phase]);
  // UI taps must not also count as "tap to place" in the AR session.
  const noSelect = (el: HTMLElement | null) => { el?.addEventListener('beforexrselect', ev => ev.preventDefault()); };

  return <div ref={overlay} className={`livear ${phase}`}>
    {phase === 'intro' || phase === 'loading' ? <main className="phone">
      <div className="phone-brand"><span className="brandmark">◎</span><b>PlanSight</b><em>LIVE AR</em></div>
      <h1>Build it on your table.</h1>
      <p>Your camera opens, PlanSight finds the table, and the building constructs itself on it. Then ask questions: the evidence lights up right there, in the room.</p>
      {supported === false ? <><p className="phone-err">This phone's browser doesn't support live AR (WebXR). On iPhone, use the Quick Look version instead.</p><a className="btn-primary big" href={fallbackUrl}>Open AR viewer →</a></>
        : <button className="btn-primary big" disabled={phase === 'loading' || supported === null} onClick={() => void start()}>{phase === 'loading' ? 'Loading the building…' : '📷 Start camera AR'}</button>}
      {err && <p className="phone-err">{err}</p>}
      <a className="btn-ghost" href={fallbackUrl}>3D preview instead</a>
    </main> : <>
      <div className="xr-top" ref={noSelect}>
        {phase === 'scanning' ? <div className={`xr-hint ${surface ? 'found' : ''}`}>{surface ? <><span>✓ Surface found</span><b>Tap anywhere to build here</b></> : <><span><i className="pulse" />{scanSecs < 4 ? 'Point at the table and move the phone slowly side to side…' : scanSecs < 9 ? 'Keep moving slowly. Tilt down a little so the table fills the view.' : 'Plain or shiny tables are hard to track: put a sheet of paper, a phone case or a book on it.'}</span><b>a lime ring appears when it locks on</b></>}</div>
          : <div className="xr-card">
            <div className="xr-count"><span>{q ? short(q) : 'Ask a question'}</span><b className={count[1] && count[0] >= count[1] ? 'done' : ''}>{busy ? '…' : ans && !ans.abstained ? (count[1] ? count[0] : String(ans.value)) : '—'}</b></div>
            {ans && !ans.abstained && <small>{count[1] ? `${count[1]} lit in lime on the model` : 'exact answer from the drawing'} · ${(ans.cost_usd ?? 0).toFixed(5)}</small>}
            {ans?.abstained && <small className="warn">{ans.reason}</small>}
          </div>}
        <button className="xr-x" onClick={() => engine.current?.end()}>✕</button>
      </div>
      {phase === 'scanning' && scanSecs >= 5 && !surface && <div className="xr-bottom" ref={noSelect}><button className="btn-primary big" onClick={() => engine.current?.placeInFront()}>Place it in front of me</button></div>}
      {phase === 'placed' && <div className="xr-bottom" ref={noSelect}>
        <div className="ar-chips">{examples.map(e => <button key={e} className={e === q ? 'on' : ''} disabled={busy} onClick={() => void ask(e)}>{short(e)}</button>)}</div>
        <form className="ar-ask" onSubmit={e => { e.preventDefault(); if (input.trim()) { void ask(input.trim()); setInput(''); } }}><input value={input} onChange={e => setInput(e.target.value)} placeholder="Ask anything · any language" /><button className="btn-primary">Ask</button></form>
        <button className="xr-move" onClick={() => { engine.current?.replace(); setPhase('scanning'); }}>↺ Move the building</button>
      </div>}
    </>}
  </div>;
}
