import { useEffect, useMemo, useRef, useState } from 'react';
import './App.css';
import Voice from './Voice';

type Drawing = { path: string; source: string; title: string; thumbnail_url: string; sample_question?: string; is_model?: boolean; model_path?: string | null; sheet_path?: string };
type Evidence = { file: string; page: number; bbox: [number, number, number, number]; polygon?: [number, number][] | null; label?: string; crop_url?: string | null; highlight_url?: string | null };
type Answer = { value?: unknown; unit?: string | null; evidence?: Evidence[]; method?: string; confidence?: number; explanation?: string; solver?: string; latency_ms?: number; cost_usd?: number; naive_cost_usd?: number; abstained?: boolean; reason?: string; cached?: boolean; share_url?: string | null; model_fact?: { element: string; guid?: string; property: string; value: unknown; element_name?: string } };
type Stats = { enabled: boolean; questions?: number; answered?: number; cost_usd?: number; naive_cost_usd?: number; corrections?: number };
type AecvPlan = { image_width: number; image_height: number; split: string; gold: Record<string, number>; frontier: Record<string, Record<string, number | null>>; frontier_cost_usd: Record<string, number | null>; plansight: Record<string, { count: number; evidence: { bbox: [number, number, number, number]; label: string }[]; note?: string | null }>; plansight_cost_usd: number; nemotron?: { counts: Record<string, number | null>; cost_usd: number; latency_ms: number; model: string } | null; trace?: Record<string, { rule: string; voters: Record<string, number | null>; used: string | string[]; after_merge?: number }> };

const nemoNote: Record<string, string> = {
  Door: 'Symbols are counted by the fine-tuned detector. Nemotron alone gets 13% of door counts right, so its count is shown but not used.',
  Window: 'Symbols are counted by the fine-tuned detector. Nemotron alone gets 7% of window counts right, so its count is shown but not used.',
  Bedroom: 'Nemotron reads the room labels on the whole plan and is one of three voters. Adding it lifted bedrooms from 77% to 85% on unseen plans.',
  Toilet: 'Nemotron reads the room labels on the whole plan and is one of three voters (the median wins).',
};
const sourceNames: Record<string, string> = { swiss_dwellings: 'Swiss dwellings · vector', ifc_models: 'IFC / BIM models', cubicasa5k: 'CubiCasa · raster scans' };
const modelNames: Record<string, string> = { gemini_35_flash: 'Gemini 3.5 Flash', gemini_3_pro_preview: 'Gemini 3 Pro', claude_fable_5: 'Claude Fable 5', claude_opus_48: 'Claude Opus 4.8', openai_gpt_55: 'GPT-5.5', qwen_37_plus: 'Qwen 3.7 Plus', gemma_4_31b_it: 'Gemma 4 31B', nvidia_nemotron_3_nano_omni_30b: 'Nemotron 3 Nano Omni' };
// Split B (60 unseen plans), exact match. PlanSight vs the best published frontier model per kind.
const splitB: [string, number, number, string][] = [['Door', 43, 43, 'Gemini 3.5 Flash'], ['Window', 38, 38, 'Gemini 3.5 Flash'], ['Toilet', 80, 87, 'Claude Fable 5'], ['Bedroom', 85, 93, 'Gemini 3.5 Flash']];
const thinking: Record<string, string[]> = {
  cubicasa5k: ['Routing question → template bank', 'Rasterising the scanned sheet', 'Fine-tuned YOLO11 detector · ONNX · CPU', 'Reading room labels with OCR', 'Merging overlapping boxes', 'Checking every box against the sheet'],
  swiss_dwellings: ['Routing question → template bank', 'Opening the vector PDF text layer', 'Matching room labels to outlines', 'Exact geometry · no model needed', 'Collecting evidence regions'],
  ifc_models: ['Routing question → template bank', 'Opening the IFC model with ifcopenshell', 'Querying building elements', 'Exact BIM facts · no model needed', 'Linking the answer to its element'],
};

const money = (v: number) => v === 0 ? '$0' : v < 0.001 ? `$${v.toFixed(5)}` : v < 1 ? `$${v.toFixed(4)}` : `$${v.toFixed(2)}`;

function useCountUp(target: number, ms: number, key: unknown) {
  const [v, setV] = useState(0);
  useEffect(() => {
    let raf = 0; const t0 = performance.now();
    const tick = (t: number) => { const p = Math.min(1, (t - t0) / ms); setV(target * (1 - Math.pow(1 - p, 3))); if (p < 1) raf = requestAnimationFrame(tick); };
    raf = requestAnimationFrame(tick); return () => cancelAnimationFrame(raf);
  }, [target, ms, key]);
  return v;
}

/** Reveals n items one by one; returns how many are visible. */
function useReveal(n: number, key: unknown, totalMs = 2200) {
  const [shown, setShown] = useState(0);
  useEffect(() => {
    setShown(0); if (!n) return;
    const step = Math.max(70, Math.min(420, totalMs / n)); let i = 0;
    const start = setTimeout(function next() { i += 1; setShown(i); if (i < n) timer = setTimeout(next, step); }, 450);
    let timer = start; return () => clearTimeout(timer);
  }, [n, key, totalMs]);
  return [shown, () => setShown(n)] as const;
}

function CostRace({ cost, naive, k, label = 'naive frontier model, full sheet', cached = false }: { cost: number; naive: number; k: unknown; label?: string; cached?: boolean }) {
  const a = useCountUp(cost, 1400, k), b = useCountUp(naive, 1400, k);
  const ratio = cost > 0 ? Math.round(naive / cost) : null;
  return <div className="race">
    <div className="race-row ours"><span>PlanSight</span><i><em style={{ width: `${Math.max(1.5, naive ? (cost / naive) * 100 : 0)}%` }} /></i><b>{money(a)}</b></div>
    <div className="race-row them"><span>{label}</span><i><em style={{ width: '100%' }} /></i><b>{money(b)}</b></div>
    <div className="race-foot">{ratio ? <><strong>{ratio.toLocaleString()}×</strong> cheaper</> : <><strong>$0</strong> {cached ? 'cached · repeat questions are free' : 'exact answer · no model call'}</>}</div>
  </div>;
}

function Intro({ onEnter, onBench }: { onEnter: () => void; onBench: () => void }) {
  const pct = useCountUp(43, 1600, 'intro');
  return <div className="intro">
    <div className="intro-grid" />
    <div className="intro-inner">
      <span className="kicker">AECV-Bench · 120 real floor plans · 30 frontier AI models</span>
      <h1>The best AI model in the world counts the doors on a floor plan correctly <span className="hot">{Math.round(pct)}%</span> of the time.</h1>
      <p>Bigger models won't fix that. It's a perception problem, not a reasoning one. <b>PlanSight</b> answers questions about construction drawings with fine-tuned detectors, exact geometry and NVIDIA Nemotron, <b>shows you every item it counted</b>, and costs a fraction of a cent.</p>
      <div className="intro-stats"><div><b>62%</b><span>PlanSight on unseen plans<br />(best frontier: 65%)</span></div><div><b>1/60</b><span>of the cost of the<br />cheapest frontier model</span></div><div><b>99.5%</b><span>on Stoa's vector plans<br />and IFC models, $0</span></div></div>
      <div className="intro-cta"><button className="btn-primary" onClick={onEnter}>Ask a drawing →</button><button className="btn-ghost" onClick={onBench}>Race the frontier models</button></div>
    </div>
  </div>;
}

function App() {
  const [intro, setIntro] = useState(() => !new URLSearchParams(location.search).has('skip'));
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  const [selected, setSelected] = useState<Drawing | null>(null);
  const [examples, setExamples] = useState<string[]>([]);
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [answerKey, setAnswerKey] = useState(0);
  const [busy, setBusy] = useState(false);
  const [thinkStep, setThinkStep] = useState(0);
  const [stats, setStats] = useState<Stats | null>(null);
  const loadStats = () => { fetch('/api/stats').then(r => r.ok ? r.json() : null).then(setStats).catch(() => {}); };
  useEffect(loadStats, []);
  const [size, setSize] = useState({ width: 1, height: 1 });
  const [rendered, setRendered] = useState({ width: 1, height: 1 });
  const [zoom, setZoom] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [drag, setDrag] = useState<{ x: number; y: number; ox: number; oy: number } | null>(null);
  const [rejectedMain, setRejectedMain] = useState<number[]>([]);
  const [view, setView] = useState<'demo' | 'aecv'>('demo');
  const [aecv, setAecv] = useState<Record<string, AecvPlan>>({});
  const [aecvPlan, setAecvPlan] = useState('2000-0011');
  const [aecvKind, setAecvKind] = useState('Door');
  const [rejected, setRejected] = useState<number[]>([]);
  const [added, setAdded] = useState<[number, number, number, number][]>([]);
  const [addMode, setAddMode] = useState(false);
  const [aecvImageSize, setAecvImageSize] = useState<[number, number]>([0, 0]);
  const aecvImage = useRef<HTMLImageElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);

  useEffect(() => { fetch('/api/drawings').then(r => r.json()).then((items: Drawing[]) => { setDrawings(items); const first = items.find(d => d.source === 'cubicasa5k') || items[0]; if (first) setSelected(first); }); }, []);
  useEffect(() => { fetch('/api/aecv/plans').then(r => r.ok ? r.json() : fetch('/aecv/plans.json').then(x => x.json())).then(setAecv).catch(() => {}); }, []);
  useEffect(() => {
    if (!selected) return;
    setAnswer(null); setZoom(1); setOffset({ x: 0, y: 0 }); setQuestion(''); setRejectedMain([]);
    fetch(`/api/examples?path=${encodeURIComponent(selected.path)}`).then(r => r.ok ? r.json() : { examples: [] }).then(d => setExamples(d.examples || []));
    fetch(`/api/meta?path=${encodeURIComponent(selected.path)}`).then(r => r.json()).then(d => { if (d.width) setSize({ width: d.width, height: d.height }); });
  }, [selected]);
  // React registers wheel listeners as passive, so preventDefault() there can't stop the browser's page zoom.
  useEffect(() => {
    const el = canvasRef.current; if (!el) return;
    const onWheel = (e: WheelEvent) => { if (e.ctrlKey || e.metaKey) { e.preventDefault(); setZoom(z => Math.max(1, Math.min(4, z + (e.deltaY < 0 ? .15 : -.15)))); } };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [view, intro]);
  useEffect(() => { if (!busy) return; setThinkStep(0); const t = setInterval(() => setThinkStep(s => s + 1), 420); return () => clearInterval(t); }, [busy]);

  const displayPath = useMemo(() => answer?.evidence?.find(e => e.file)?.file || selected?.path || '', [answer, selected]);
  const imageUrl = displayPath ? `/api/render?path=${encodeURIComponent(displayPath)}&page=0` : '';
  const evidence = answer?.evidence || [];
  const unitScaleX = rendered.width / size.width;
  const unitScaleY = rendered.height / size.height;
  const [shown, skipReveal] = useReveal(evidence.length, answerKey);
  const isCount = answer?.unit === 'count' || (typeof answer?.value === 'number' && Number.isInteger(answer.value) && !answer?.unit);
  const revealDone = shown >= evidence.length;
  const liveCount = isCount && evidence.length ? Math.max(0, shown - rejectedMain.filter(i => i < shown).length) : null;
  const numeric = typeof answer?.value === 'number' ? answer.value as number : Number.NaN;
  const rolled = useCountUp(Number.isFinite(numeric) ? numeric : 0, 1500, answerKey);
  const thinkLines = thinking[selected?.source || 'cubicasa5k'] || thinking.cubicasa5k;

  const ask = async (q: string = question): Promise<Answer | null> => {
    if (!selected || !q.trim() || busy) return null;
    setQuestion(q); setBusy(true); setAnswer(null); setZoom(1); setOffset({ x: 0, y: 0 }); setRejectedMain([]);
    const minWait = new Promise(r => setTimeout(r, 1300)); // let the "thinking" trace play even on $0 instant answers
    try {
      const response = await fetch('/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: selected.path, question: q }) });
      const result: Answer = await response.json(); await minWait;
      setAnswer(result); setAnswerKey(k => k + 1); setTimeout(loadStats, 1500);
      const img = imageRef.current;
      if (img && result.evidence?.length === 1) {
        const [x0, y0, x1, y1] = result.evidence[0].bbox;
        const sx = img.clientWidth / size.width, sy = img.clientHeight / size.height;
        const bw = (x1 - x0) * sx, bh = (y1 - y0) * sy;
        const z = Math.max(1, Math.min(3, 0.5 * Math.min(img.clientWidth / Math.max(bw, 1), img.clientHeight / Math.max(bh, 1))));
        const dx = ((x0 + x1) / 2) * sx - img.clientWidth / 2, dy = ((y0 + y1) / 2) * sy - img.clientHeight / 2;
        setTimeout(() => { setZoom(z); setOffset({ x: -dx * z, y: -dy * z }); }, 900);
      }
      return result;
    } catch { await minWait; const a = { abstained: true, reason: 'The API could not be reached.' }; setAnswer(a); setAnswerKey(k => k + 1); return a; }
    finally { setBusy(false); }
  };

  const route = useMemo(() => {
    const m = answer?.explanation?.match(/routed by (.+?) to (.+?)\./i);
    return m ? { by: m[1], to: m[2].replace(/[{}']/g, '').replace(/:\s*/g, ': ') } : null;
  }, [answer]);
  const pipeline: [string, string, boolean][] = answer && !answer.abstained ? [
    ['Question', question.length > 34 ? question.slice(0, 32) + '…' : question, true],
    ['Router', route ? `${route.by} → ${route.to}` : 'template bank', true],
    ['Solver', `${answer.solver || '—'} · ${answer.cached ? 'cached' : answer.method || 'deterministic'}`, true],
    ['Evidence', evidence.length ? `${Math.min(shown, evidence.length)} / ${evidence.length} regions` : answer.model_fact ? 'IFC element' : 'text layer', shown > 0 || !evidence.length],
    ['Answer', `${String(answer.value)} ${answer.unit && answer.unit !== 'count' ? answer.unit : ''}`, revealDone],
  ] : [];

  const openDrawing = (query: string) => {
    const q = query.toLowerCase(); const words = q.split(/\s+/).filter(Boolean);
    const hit = drawings.find(d => words.every(w => `${d.title} ${d.source} ${d.path}`.toLowerCase().includes(w))) || drawings.find(d => words.some(w => `${d.title} ${d.source}`.toLowerCase().includes(w)));
    if (!hit) return `No drawing matches "${query}". Available: ${drawings.map(d => d.title).join(', ')}`;
    setView('demo'); setSelected(hit); return `Opened ${hit.title} (${sourceNames[hit.source] || hit.source}).`;
  };
  const voiceContext = selected ? `${selected.title} (${sourceNames[selected.source] || selected.source}${selected.is_model ? ', 3D IFC model' : ''}). Example question: ${examples[0] || selected.sample_question || ''}` : 'none';

  // ---------- AECV benchmark view ----------
  const plan = aecv[aecvPlan];
  const kindData = plan?.plansight[aecvKind] || { count: 0, evidence: [] };
  const [aShown, aSkip] = useReveal(kindData.evidence.length, `${aecvPlan}-${aecvKind}-${view}`, 2400);
  const activeCount = Math.max(0, Math.min(aShown, kindData.count) - rejected.filter(i => i < aShown).length + added.length);
  const aDone = aShown >= kindData.evidence.length;
  const postFeedback = (bbox: number[], action: string) => { void fetch('/api/feedback', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ plan: aecvPlan, kind: aecvKind, bbox, action }) }); };
  const toggleBox = (index: number) => { const box = kindData.evidence[index]?.bbox; if (!box) return; const reject = !rejected.includes(index); setRejected(v => reject ? [...v, index] : v.filter(x => x !== index)); postFeedback(box, reject ? 'reject' : 'add'); };
  const addBox = (e: React.MouseEvent<HTMLDivElement>) => { if (!addMode || !aecvImage.current) return; const el = aecvImage.current, r = el.getBoundingClientRect(), sx = (plan?.image_width || el.naturalWidth) / r.width, sy = (plan?.image_height || el.naturalHeight) / r.height, x = (e.clientX - r.left) * sx, y = (e.clientY - r.top) * sy; const b: [number, number, number, number] = [Math.max(0, x - 18), Math.max(0, y - 18), x + 18, y + 18]; setAdded(v => [...v, b]); postFeedback(b, 'add'); setAddMode(false); };
  const pickRandomPlan = () => { const ids = Object.keys(aecv).filter(id => aecv[id].split === 'B'); if (ids.length) { setAecvPlan(ids[Math.floor(Math.random() * ids.length)]); setRejected([]); setAdded([]); } };
  const frontierRows = plan ? Object.entries(plan.frontier).map(([m, a]) => ({ m, v: a[aecvKind], cost: plan.frontier_cost_usd[m] })).sort((x, y) => (y.cost ?? 0) - (x.cost ?? 0)) : [];
  const gold = plan?.gold[aecvKind];
  const frontierRight = frontierRows.filter(r => r.v === gold).length;
  const plansightRight = plan ? plan.plansight[aecvKind]?.count === gold : false;

  const header = <header className="topbar">
    <button className="brand" onClick={() => setIntro(true)}><span className="brandmark">◎</span><span><b>PlanSight</b><small>make blueprints talk</small></span></button>
    <nav className="tabs"><button className={view === 'demo' ? 'on' : ''} onClick={() => setView('demo')}>Ask a drawing</button><button className={view === 'aecv' ? 'on' : ''} onClick={() => setView('aecv')}>Frontier vs PlanSight</button></nav>
    <div className="ticker">{stats?.enabled && stats.questions ? <><i className="pulse" /><b>{stats.questions.toLocaleString()}</b> questions · <b>{money(stats.cost_usd ?? 0)}</b> spent vs <b>{money(stats.naive_cost_usd ?? 0)}</b> frontier · <b>{stats.corrections ?? 0}</b> corrections <em>Aiven Postgres</em></> : <><i className="pulse" />live · CPU · scales to zero</>}</div>
  </header>;

  if (intro) return <Intro onEnter={() => { setIntro(false); setView('demo'); }} onBench={() => { setIntro(false); setView('aecv'); }} />;

  if (view === 'aecv') return <main className="shell">{header}
    <section className="scoreboard">
      <div className="sb-title"><span className="kicker">Held-out split B · 60 plans we never tuned on · exact match</span><h2>PlanSight vs the best frontier model</h2></div>
      {splitB.map(([k, ours, best, who]) => <button key={k} className={`sb-kind ${aecvKind === k ? 'on' : ''}`} onClick={() => { setAecvKind(k); setRejected([]); setAdded([]); }}>
        <span>{k}s</span>
        <div className="sb-bar ours"><i><em style={{ width: `${ours}%` }} /></i><b>{ours}%</b></div>
        <div className="sb-bar best"><i><em style={{ width: `${best}%` }} /></i><b>{best}%</b></div>
        <small>vs {who}</small>
      </button>)}
      <div className="sb-cost"><b>$0.0005</b><span>PlanSight / plan</span><b className="dim">$0.031–$0.224</b><span>frontier / plan</span></div>
    </section>
    <div className="bench-controls">
      <label>PLAN<select value={aecvPlan} onChange={e => { setAecvPlan(e.target.value); setRejected([]); setAdded([]); }}>{Object.keys(aecv).sort().map(id => <option key={id} value={id}>{id} · split {aecv[id].split}</option>)}</select></label>
      <button className="btn-ghost sm" onClick={pickRandomPlan}>🎲 Random unseen plan</button>
      <button className={`btn-ghost sm ${addMode ? 'armed' : ''}`} onClick={() => setAddMode(v => !v)}>{addMode ? 'Tap the plan to add…' : '+ Add a missed item'}</button>
      {!aDone && <button className="btn-ghost sm" onClick={aSkip}>Skip replay ⏭</button>}
    </div>
    {plan && <div className="bench-grid">
      <section className="panel frontier" key={`${aecvPlan}-${aecvKind}`}>
        <div className="panel-head"><span className="kicker">Frontier AI answers · published</span><h3>How many {aecvKind.toLowerCase()}s?</h3><div className="gold">ground truth <b>{gold}</b></div></div>
        {frontierRows.map((r, i) => { const ok = r.v === gold; return <div className={`f-row ${ok ? 'ok' : 'bad'}`} key={r.m} style={{ animationDelay: `${0.12 * i}s` }}><span className="mark">{ok ? '✓' : '✕'}</span><b>{modelNames[r.m] || r.m}</b><strong>{r.v ?? '—'}</strong><small>{r.cost != null ? `${money(r.cost)}/plan` : 'cost n/a'}</small></div>; })}
        {plan.nemotron && (() => { const v = plan.nemotron.counts[aecvKind], ok = v === gold; return <div className={`f-row nemo ${ok ? 'ok' : 'bad'}`} style={{ animationDelay: `${0.12 * frontierRows.length}s` }}><span className="mark">{ok ? '✓' : '✕'}</span><b>Nemotron 3.5 Super VL alone</b><strong>{v ?? '—'}</strong><small>{money(plan.nemotron.cost_usd)}/plan · self-hosted on Verda</small></div>; })()}
        <div className="f-summary"><b>{frontierRight}/{frontierRows.length}</b> frontier models right on this plan</div>
      </section>
      <section className="panel stage-panel">
        <div className="hud">
          <div className="hud-count"><span className="kicker">PlanSight · {aecvKind.toLowerCase()}s</span><b className={aDone ? 'done' : ''}>{activeCount}</b>{aDone && <span className={`verdict ${activeCount === gold ? 'ok' : 'bad'}`}>{activeCount === gold ? '✓ matches ground truth' : `✕ ground truth ${gold}`}</span>}</div>
          <CostRace cost={plan.plansight_cost_usd} naive={plan.frontier_cost_usd.claude_fable_5 ?? 0.077} k={`${aecvPlan}-${aecvKind}`} label="Claude Fable 5, same plan" />
        </div>
        {plan.trace?.[aecvKind] && (() => { const t = plan.trace![aecvKind], used = Array.isArray(t.used) ? t.used : [t.used]; return <div className="voters"><div className="voters-head"><span className="kicker">How PlanSight got {kindData.count}</span><em>{t.rule}{t.after_merge != null && t.after_merge !== t.voters.detector ? ` (${t.voters.detector} boxes → ${t.after_merge})` : ''}</em></div><div className="voter-row">{Object.entries(t.voters).map(([name, n], i) => { const nemo = name === 'nemotron'; return <div key={name} style={{ animationDelay: `${0.15 * i + 0.3}s` }} className={`voter ${used.includes(name) ? 'used' : ''} ${nemo ? 'nemo' : ''}`}><small>{nemo ? 'Nemotron 3.5 Super VL' : name}</small><b>{n ?? '—'}</b>{nemo && plan.nemotron && <i>{money(plan.nemotron.cost_usd)} · {(plan.nemotron.latency_ms / 1000).toFixed(1)} s</i>}{used.includes(name) && <span className="voter-tag">used</span>}</div>; })}</div><p>{nemoNote[aecvKind]}</p></div>; })()}
        <div className={`plan-wrap ${addMode ? 'adding' : ''} ${aDone ? '' : 'scanning'}`} onClick={addBox}>
          <div className="plan-stage">
            <img ref={aecvImage} onLoad={e => setAecvImageSize([e.currentTarget.naturalWidth, e.currentTarget.naturalHeight])} src={`/aecv/img/${aecvPlan}.jpg`} alt={`Architectural plan ${aecvPlan}`} />
            {!aDone && <div className="scanline" />}
            {aecvImageSize[0] > 0 && <svg viewBox={`0 0 ${plan.image_width || aecvImageSize[0]} ${plan.image_height || aecvImageSize[1]}`} preserveAspectRatio="none" style={{ fontSize: Math.max(14, (plan.image_width || aecvImageSize[0]) / 30) }}>
              {kindData.evidence.slice(0, aShown).map((ev, i) => { const [x0, y0, x1, y1] = ev.bbox; const rej = rejected.includes(i); return <g key={i} className={`ev ${rej ? 'rejected' : ''}`} onClick={e => { e.stopPropagation(); toggleBox(i); }}><rect className="ring" x={x0} y={y0} width={x1 - x0} height={y1 - y0} /><rect className="under" x={x0} y={y0} width={x1 - x0} height={y1 - y0} /><rect x={x0} y={y0} width={x1 - x0} height={y1 - y0} /><text x={x0} y={y0 - (plan.image_width || 1000) / 250}>{rej ? '✕' : i + 1}</text></g>; })}
              {added.map((b, i) => <rect key={`added-${i}`} className="added" x={b[0]} y={b[1]} width={b[2] - b[0]} height={b[3] - b[1]} />)}
            </svg>}
          </div>
        </div>
        <p className="hint">Every count is a box you can check. <b>Tap a box</b> to reject it, the count updates and the correction is logged as training data. {plansightRight ? '' : plan.plansight[aecvKind]?.note || ''}</p>
      </section>
    </div>}
  </main>;

  // ---------- main demo view ----------
  return <main className="shell">{header}
    <div className="workspace">
      <aside className="panel library">
        <div className="panel-head"><span className="kicker">Stoa dataset · {drawings.length} drawings</span><h3>Pick a drawing</h3></div>
        {Object.keys(sourceNames).map(source => <section className="source" key={source}><h4>{sourceNames[source]}</h4>
          {drawings.filter(d => d.source === source).map(d => <button className={`d-row ${selected?.path === d.path ? 'on' : ''}`} key={d.path} onClick={() => setSelected(d)}><img src={d.thumbnail_url} alt="" /><span><b>{d.title}</b><small>{d.sample_question || d.path}</small></span></button>)}
        </section>)}
      </aside>

      <section className="panel stage-panel main-stage">
        <div className="stage-head">
          <div><span className="kicker">{selected?.is_model ? 'IFC model · BIM facts' : 'Sheet viewer'}</span><h3>{selected?.title || 'Loading drawings…'}</h3></div>
          <div className="zoom">{selected?.is_model && selected.sheet_path && <button onClick={() => setSelected({ ...selected, path: selected.sheet_path!, title: selected.sheet_path!.split('/').pop() || selected.title, is_model: false })}>2D sheet</button>}{!selected?.is_model && selected?.model_path && <button onClick={() => setSelected({ ...selected, sheet_path: selected.path, path: selected.model_path!, title: `${selected.title} · IFC model`, is_model: true })}>Model facts</button>}{!selected?.is_model && <><button onClick={() => setZoom(z => Math.max(1, z - .25))}>−</button><span>{Math.round(zoom * 100)}%</span><button onClick={() => setZoom(z => Math.min(4, z + .25))}>+</button><button onClick={() => { setZoom(1); setOffset({ x: 0, y: 0 }); }}>Fit</button></>}</div>
        </div>
        <div className={`canvas ${busy ? "busy" : ""} ${evidence.length ? "has-ev" : ""}`} ref={canvasRef} onPointerDown={e => { if (zoom > 1 && (e.target as Element).tagName !== 'rect') { (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); setDrag({ x: e.clientX, y: e.clientY, ox: offset.x, oy: offset.y }); } }} onPointerMove={e => { if (drag) setOffset({ x: drag.ox + e.clientX - drag.x, y: drag.oy + e.clientY - drag.y }); }} onPointerUp={() => setDrag(null)}>
          {(liveCount !== null || (answer && !answer.abstained && Number.isFinite(numeric))) && <div className="stage-counter"><span>{answer?.unit && answer.unit !== 'count' ? answer.unit : 'count'}</span><b className={revealDone ? 'done' : ''}>{liveCount !== null ? liveCount : Number.isInteger(numeric) ? Math.round(rolled) : rolled.toFixed(2)}</b></div>}
          {busy && <div className="think">{thinkLines.slice(0, Math.min(thinkLines.length, thinkStep + 1)).map((l, i) => <div key={i} className={i === Math.min(thinkLines.length - 1, thinkStep) ? 'cur' : 'past'}><i>{i === Math.min(thinkLines.length - 1, thinkStep) ? '◌' : '✓'}</i>{l}</div>)}</div>}
          {selected?.is_model && !evidence.length ? <div className="model-card"><span className="model-icon">⬢</span><h3>BIM model fact</h3>{answer?.model_fact ? <dl><dt>Element</dt><dd>{answer.model_fact.element}{answer.model_fact.element_name ? ` · ${answer.model_fact.element_name}` : ''}</dd><dt>GlobalId</dt><dd>{answer.model_fact.guid || 'Model aggregate'}</dd><dt>Property</dt><dd>{answer.model_fact.property}: {String(answer.model_fact.value)}</dd></dl> : <p>This is a 3D building model. Ask a question to see the exact element, GlobalId and property behind the answer.</p>}</div>
            : selected && <div className="sheet-transform" style={{ transform: `translate(${offset.x}px,${offset.y}px) scale(${zoom})` }}>
              <img ref={imageRef} className="sheet-image" src={imageUrl} onLoad={e => setRendered({ width: e.currentTarget.naturalWidth, height: e.currentTarget.naturalHeight })} alt="Selected architectural drawing" />
              {busy && <div className="scanline" />}
              {evidence.length > 0 && <svg className={`evidence-layer ${revealDone ? '' : 'revealing'}`} viewBox={`0 0 ${rendered.width} ${rendered.height}`} preserveAspectRatio="none" style={{ fontSize: Math.max(14, rendered.width / 28) }}>
                {evidence.slice(0, shown).map((ev, i) => { const rej = rejectedMain.includes(i); const lbl = isCount ? (rej ? '✕' : String(i + 1 - rejectedMain.filter(j => j < i).length)) : (ev.label || `Evidence ${i + 1}`); const x0 = ev.bbox[0] * unitScaleX, y0 = ev.bbox[1] * unitScaleY, w = (ev.bbox[2] - ev.bbox[0]) * unitScaleX, h = (ev.bbox[3] - ev.bbox[1]) * unitScaleY;
                  return <g key={i} className={`ev ${rej ? 'rejected' : ''}`} onClick={() => isCount && setRejectedMain(v => v.includes(i) ? v.filter(x => x !== i) : [...v, i])}>
                    {ev.polygon?.length ? <><polygon className="ring" points={ev.polygon.map(([x, y]) => `${x * unitScaleX},${y * unitScaleY}`).join(' ')} /><polygon points={ev.polygon.map(([x, y]) => `${x * unitScaleX},${y * unitScaleY}`).join(' ')} /></> : <><rect className="ring" x={x0} y={y0} width={w} height={h} /><rect className="under" x={x0} y={y0} width={w} height={h} /><rect x={x0} y={y0} width={w} height={h} /></>}
                    <text x={x0} y={Math.max(rendered.width / 50, y0 - rendered.width / 200)}>{lbl}</text></g>; })}
              </svg>}
            </div>}
        </div>
        {pipeline.length > 0 && <div className="pipeline" key={answerKey}>{pipeline.map(([k, v, on], i) => <div key={k} className={`step ${on ? 'on' : ''}`} style={{ animationDelay: `${i * 0.12}s` }}><span>{k}</span><b>{v}</b></div>)}</div>}
        <div className="stage-foot"><span>{evidence.length ? <>{evidence.length} evidence region{evidence.length === 1 ? '' : 's'}{isCount ? ' · tap a box to reject it' : ''}{!revealDone && <button className="link" onClick={skipReveal}>skip replay</button>}</> : 'Evidence is drawn on the sheet after an answer'}</span><span>drag to pan · ctrl + scroll to zoom</span></div>
        {evidence.some(e => e.crop_url) && revealDone && <div className="gallery"><div className="gallery-head"><span className="kicker">Evidence crops · zoomed by Cloudinary</span>{answer?.share_url && <a href={answer.share_url} target="_blank" rel="noreferrer">Share evidence sheet ↗</a>}</div><div className="gallery-row">{evidence.filter(e => e.crop_url).slice(0, 12).map((e, i) => <a key={i} href={e.crop_url!} target="_blank" rel="noreferrer" title={e.label || `region ${i + 1}`} style={{ animationDelay: `${i * 0.05}s` }}><img src={e.crop_url!} alt={e.label || `evidence ${i + 1}`} loading="lazy" /></a>)}</div></div>}
      </section>

      <aside className="panel ask">
        <div className="panel-head"><span className="kicker">Ask this drawing · any language</span><h3>What do you want to know?</h3></div>
        <div className="ask-box"><textarea value={question} onChange={e => setQuestion(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void ask(); } }} placeholder="How many doors are on this floor? · Montako ovea? · Wie viele Türen?" /><button className="btn-primary" onClick={() => void ask()} disabled={busy || !question.trim()}>{busy ? 'Reading…' : 'Ask ↗'}</button></div>
        <div className="chips">{examples.map(q => <button key={q} disabled={busy} onClick={() => void ask(q)}>{q}</button>)}</div>
        {answer && <div className={`answer ${answer.abstained ? 'abstain' : ''}`} key={answerKey}>
          {answer.abstained ? <><span className="kicker warn">Not confident enough</span><h3>PlanSight won't guess</h3><p>{answer.reason}</p></> : <>
            <div className="answer-top"><span className="kicker">Answer</span><span className="badge">{answer.cached ? 'cached · $0' : answer.method || 'deterministic'}</span></div>
            <div className="answer-value">{liveCount !== null ? liveCount : String(answer.value)}<small>{answer.unit && answer.unit !== 'count' ? answer.unit : ''}</small></div>
            {(answer.confidence ?? 1) < 1 && <div className="conf"><span>confidence</span><i><em style={{ width: `${Math.round((answer.confidence ?? 1) * 100)}%` }} /></i><b>{Math.round((answer.confidence ?? 1) * 100)}%</b></div>}
            {rejectedMain.length > 0 && <div className="corrected">You rejected {rejectedMain.length} box{rejectedMain.length > 1 ? 'es' : ''}: corrected from {String(answer.value)}</div>}
            <p className="explain">{answer.explanation}</p>
          </>}
          <div className="cost"><div className="cost-head"><span className="kicker">What this question cost</span><span>{answer.latency_ms != null ? `${(answer.latency_ms / 1000).toFixed(2)} s` : ''}</span></div><CostRace cost={answer.cost_usd ?? 0} naive={answer.naive_cost_usd ?? 0} k={answerKey} cached={!!answer.cached} /></div>
        </div>}
        <div className="note"><span>✦</span> Every answer is pinned to a region of the drawing you can check in seconds. If the evidence is weak, PlanSight abstains instead of guessing.</div>
      </aside>
    </div>
    <Voice ask={ask} openDrawing={openDrawing} context={voiceContext} />
  </main>;
}

export default App;
