import { useEffect, useMemo, useRef, useState } from 'react';
import './App.css';

type Drawing = { path: string; source: string; title: string; thumbnail_url: string; sample_question?: string; is_model?: boolean; model_path?: string | null; sheet_path?: string };
type Evidence = { file: string; page: number; bbox: [number, number, number, number]; polygon?: [number, number][] | null; label?: string; crop_url?:string|null; highlight_url?:string|null };
type Answer = { value?: unknown; unit?: string | null; evidence?: Evidence[]; method?: string; confidence?: number; explanation?: string; solver?: string; latency_ms?: number; cost_usd?: number; naive_cost_usd?: number; abstained?: boolean; reason?: string; cached?:boolean; model_fact?: { element: string; guid?: string; property: string; value: unknown; element_name?: string } };
type AecvPlan = { image_width:number; image_height:number; split:string; gold:Record<string,number>; frontier:Record<string,Record<string,number|null>>; frontier_cost_usd:Record<string,number|null>; plansight:Record<string,{count:number;evidence:{bbox:[number,number,number,number];label:string}[];note?:string|null}>;plansight_cost_usd:number; nemotron?:{counts:Record<string,number|null>;cost_usd:number;latency_ms:number;model:string}|null; trace?:Record<string,{rule:string;voters:Record<string,number|null>;used:string|string[];after_merge?:number}> };
const nemoNote:Record<string,string>={Door:'Symbols are counted by the fine-tuned detector. Nemotron alone gets 13% of door counts right, so its count is shown but not used.',Window:'Symbols are counted by the fine-tuned detector. Nemotron alone gets 7% of window counts right, so its count is shown but not used.',Bedroom:'Nemotron reads the room labels on the whole plan and is one of three voters. Adding it lifted bedrooms from 77% to 85% on unseen plans.',Toilet:'Nemotron reads the room labels on the whole plan and is one of three voters (the median wins).'};
const sourceNames: Record<string, string> = { swiss_dwellings: 'Swiss dwellings', ifc_models: 'IFC models', cubicasa5k: 'CubiCasa plans' };

function App() {
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  const [selected, setSelected] = useState<Drawing | null>(null);
  const [examples, setExamples] = useState<string[]>([]);
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [busy, setBusy] = useState(false);
  const [size, setSize] = useState({ width: 1, height: 1 });
  const [rendered, setRendered] = useState({ width: 1, height: 1 });
  const [zoom, setZoom] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [drag, setDrag] = useState<{ x: number; y: number; ox: number; oy: number } | null>(null);
  const [view,setView]=useState<'demo'|'aecv'>('demo');
  const [aecv,setAecv]=useState<Record<string,AecvPlan>>({});
  const [aecvPlan,setAecvPlan]=useState('2000-0011');
  const [aecvKind,setAecvKind]=useState('Window');
  const [rejected,setRejected]=useState<number[]>([]);
  const [added,setAdded]=useState<[number,number,number,number][]>([]);
  const [addMode,setAddMode]=useState(false);
  const [aecvImageSize,setAecvImageSize]=useState<[number,number]>([0,0]);
  const aecvImage=useRef<HTMLImageElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);

  useEffect(() => { fetch('/api/drawings').then(r => r.json()).then((items: Drawing[]) => { setDrawings(items); if (items.length) setSelected(items[0]); }); }, []);
  useEffect(()=>{fetch('/api/aecv/plans').then(r=>r.ok?r.json():fetch('/aecv/plans.json').then(x=>x.json())).then(setAecv).catch(()=>{});},[]);
  useEffect(() => {
    if (!selected) return;
    setAnswer(null); setZoom(1); setOffset({ x: 0, y: 0 }); setQuestion('');
    fetch(`/api/examples?path=${encodeURIComponent(selected.path)}`).then(r => r.ok ? r.json() : { examples: [] }).then(d => setExamples(d.examples || []));
    fetch(`/api/meta?path=${encodeURIComponent(selected.path)}`).then(r => r.json()).then(d => { if (d.width) setSize({ width: d.width, height: d.height }); });
  }, [selected]);
  const displayPath = useMemo(() => answer?.evidence?.find(e => e.file)?.file || selected?.path || '', [answer, selected]);
  const imageUrl = displayPath ? `/api/render?path=${encodeURIComponent(displayPath)}&page=0` : '';
  const evidence = answer?.evidence || [];
  const unitScaleX = rendered.width / size.width;
  const unitScaleY = rendered.height / size.height;

  const ask = async () => {
    if (!selected || !question.trim() || busy) return;
    setBusy(true); setAnswer(null);
    try {
      const response = await fetch('/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: selected.path, question }) });
      const result: Answer = await response.json(); setAnswer(result);
      if (result.evidence?.length) {
        const [x0, y0, x1, y1] = result.evidence[0].bbox;
        const cx = ((x0 + x1) / 2) * unitScaleX; const cy = ((y0 + y1) / 2) * unitScaleY;
        setZoom(2.4); setOffset({ x: -cx * 1.4, y: -cy * 1.4 });
      }
    } catch { setAnswer({ abstained: true, reason: 'The API could not be reached.' }); }
    finally { setBusy(false); }
  };
  const cost = answer?.cost_usd ?? 0; const naive = answer?.naive_cost_usd ?? 0;
  const ratio = cost > 0 ? `${(naive / cost).toFixed(1)}× cheaper` : 'free deterministic answer';

  const plan=aecv[aecvPlan];
  const kindData=plan?.plansight[aecvKind]||{count:0,evidence:[]};
  const activeCount=Math.max(0,kindData.count-rejected.length+added.length);
  const postFeedback=(bbox:number[],action:string)=>{void fetch('/api/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({plan:aecvPlan,kind:aecvKind,bbox,action})});};
  const toggleBox=(index:number)=>{const box=kindData.evidence[index]?.bbox;if(!box)return;const reject=!rejected.includes(index);setRejected(v=>reject?[...v,index]:v.filter(x=>x!==index));postFeedback(box,reject?'reject':'add');};
  const addBox=(e:React.MouseEvent<HTMLDivElement>)=>{if(!addMode||!aecvImage.current)return;const el=aecvImage.current,r=el.getBoundingClientRect(),sx=(plan?.image_width||el.naturalWidth)/r.width,sy=(plan?.image_height||el.naturalHeight)/r.height,x=(e.clientX-r.left)*sx,y=(e.clientY-r.top)*sy;const b:[number,number,number,number]=[Math.max(0,x-18),Math.max(0,y-18),x+18,y+18];setAdded(v=>[...v,b]);postFeedback(b,'add');setAddMode(false);};

  if(view==='aecv') return <main className="aecv-shell"><header className="topbar"><button className="back-button" onClick={()=>setView('demo')}>← PlanSight</button><div><h1>Frontier vs PlanSight</h1><p>Split B · 60 unseen plans · exact match</p></div></header>
    <section className="scoreboard"><b>Split B exact-match accuracy</b>{[['Door',43],['Window',38],['Toilet',80],['Bedroom',85]].map(([k,v])=><div key={k}><span>{k}</span><i><em style={{width:`${v}%`}}/></i><strong>{v}%</strong></div>)}</section>
    <div className="aecv-controls"><label>PLAN<select value={aecvPlan} onChange={e=>{setAecvPlan(e.target.value);setRejected([]);setAdded([])}}>{Object.keys(aecv).sort().map(id=><option key={id} value={id}>{id} · split {aecv[id].split}</option>)}</select></label><label>KIND<select value={aecvKind} onChange={e=>{setAecvKind(e.target.value);setRejected([]);setAdded([])}}>{['Door','Window','Toilet','Bedroom'].map(k=><option key={k}>{k}</option>)}</select></label><button className={addMode?'add-active':''} onClick={()=>setAddMode(v=>!v)}>{addMode?'Tap the plan to add…':'+ Add missed item'}</button></div>
    {plan&&<div className="compare-grid"><section className="frontier-panel"><h2>Frontier answers <small>gold: {plan.gold[aecvKind]} {aecvKind.toLowerCase()}s</small></h2>{Object.entries(plan.frontier).map(([model,answers])=>{const value=answers[aecvKind],ok=value===plan.gold[aecvKind];return <div className="frontier-row" key={model}><span className={ok?'result-ok':'result-bad'}>{ok?'✓':'×'}</span><b>{model.replaceAll('_',' ')}</b><strong>{value??'—'}</strong><small>{plan.frontier_cost_usd[model]!=null?`$${plan.frontier_cost_usd[model]!.toFixed(5)}/plan`:'cost n/a'}</small></div>})}{plan.nemotron&&(()=>{const v=plan.nemotron.counts[aecvKind],ok=v===plan.gold[aecvKind];return <div className="frontier-row nemo-row"><span className={ok?'result-ok':'result-bad'}>{ok?'✓':'×'}</span><b>Nemotron 3.5 Super VL alone</b><strong>{v??'—'}</strong><small>${plan.nemotron.cost_usd.toFixed(5)}/plan · self-hosted on Verda · used inside PlanSight</small></div>})()}</section>
    <section className="aecv-sheet-panel"><div className="aecv-result"><div><span>PLANSIGHT · {aecvKind.toUpperCase()}</span><b>{activeCount} <small>items</small></b></div><div className="aecv-cost">${plan.plansight_cost_usd.toFixed(4)} <em>vs</em> ${(plan.frontier_cost_usd.claude_fable_5??.077).toFixed(3)}<small>PlanSight vs Claude Fable 5</small></div></div>{plan.trace?.[aecvKind]&&(()=>{const t=plan.trace![aecvKind],used=Array.isArray(t.used)?t.used:[t.used];return <div className="trace"><div className="trace-head"><span>HOW PLANSIGHT GOT {kindData.count}</span><em>{t.rule}{t.after_merge!=null&&t.after_merge!==t.voters.detector?` (${t.voters.detector} boxes → ${t.after_merge})`:''}</em></div><div className="trace-voters">{Object.entries(t.voters).map(([name,n])=>{const nemo=name==='nemotron';return <div key={name} className={`voter ${used.includes(name)?'used':''} ${nemo?'nemo':''}`}><small>{nemo?'Nemotron 3.5 Super VL':name}</small><b>{n??'—'}</b>{nemo&&plan.nemotron&&<i>${plan.nemotron.cost_usd.toFixed(5)} · {(plan.nemotron.latency_ms/1000).toFixed(1)} s</i>}{used.includes(name)&&<span className="voter-tag">used</span>}</div>})}</div><p>{nemoNote[aecvKind]}</p></div>})()}<div className={`aecv-image-wrap ${addMode?'adding':''}`} onClick={addBox}><div className="aecv-stage"><img ref={aecvImage} onLoad={e=>setAecvImageSize([e.currentTarget.naturalWidth,e.currentTarget.naturalHeight])} src={`/aecv/img/${aecvPlan}.jpg`} alt={`Architectural plan ${aecvPlan}`} />{aecvImageSize[0]>0&&<svg viewBox={`0 0 ${plan.image_width||aecvImageSize[0]} ${plan.image_height||aecvImageSize[1]}`} preserveAspectRatio="none">{kindData.evidence.map((ev,i)=><rect key={i} className={rejected.includes(i)?'rejected-box':''} x={ev.bbox[0]} y={ev.bbox[1]} width={ev.bbox[2]-ev.bbox[0]} height={ev.bbox[3]-ev.bbox[1]} onClick={e=>{e.stopPropagation();toggleBox(i)}}/>)}{added.map((b,i)=><rect key={`added-${i}`} className="added-box" x={b[0]} y={b[1]} width={b[2]-b[0]} height={b[3]-b[1]}/>)}</svg>}</div></div><p className="correction-hint">Tap a box to reject it. Add mode records a missed region. {plan.plansight[aecvKind]?.note||''}</p></section></div>}</main>;

  return <main className="app-shell">
    <header className="topbar"><div className="brandmark">P</div><div><h1>PlanSight</h1><p>Make blueprints talk</p></div><span className="live-pill"><i /> LIVE DEMO</span><span className="top-note">Evidence-backed answers from construction drawings</span></header>
    <button className="compare-launch" onClick={()=>setView('aecv')}>Frontier vs PlanSight benchmark →</button><div className="workspace">
      <aside className="picker panel"><div className="section-head"><div><span className="eyebrow">LIBRARY</span><h2>Drawings</h2></div><span className="count-pill">{drawings.length}</span></div>
        {Object.keys(sourceNames).map(source => <section className="source-group" key={source}><h3>{sourceNames[source]} <span>{drawings.filter(d => d.source === source).length}</span></h3>
          {drawings.filter(d => d.source === source).map(d => <button className={`drawing-row ${selected?.path === d.path ? 'active' : ''}`} key={d.path} onClick={() => setSelected(d)}><img src={d.thumbnail_url} alt="" /><span><b>{d.title}</b><small>{d.sample_question || d.path}</small></span><span className="row-arrow">›</span></button>)}
        </section>)}
      </aside>
      <section className="viewer-column"><div className="viewer panel"><div className="viewer-head"><div><span className="eyebrow">{selected?.is_model ? 'IFC MODEL FACTS' : 'SHEET VIEWER'}</span><h2>{selected?.title || 'Loading drawings…'}</h2></div><div className="zoom-controls">{selected?.is_model && selected.sheet_path && <button onClick={() => setSelected({ ...selected, path: selected.sheet_path!, title: selected.sheet_path!.split('/').pop() || selected.title, is_model: false })}>2D sheet</button>}{!selected?.is_model && selected?.model_path && <button onClick={() => setSelected({ ...selected, sheet_path: selected.path, path: selected.model_path!, title: `${selected.title} · IFC model`, is_model: true })}>Model facts</button>}{!selected?.is_model && <><button onClick={() => setZoom(z => Math.max(1, z - .25))}>−</button><span>{Math.round(zoom * 100)}%</span><button onClick={() => setZoom(z => Math.min(4, z + .25))}>+</button><button onClick={() => { setZoom(1); setOffset({ x: 0, y: 0 }); }}>Fit</button></>}</div></div>
          <div className="canvas" onWheel={e => { if (e.ctrlKey || e.metaKey) { e.preventDefault(); setZoom(z => Math.max(1, Math.min(4, z + (e.deltaY < 0 ? .15 : -.15)))); } }} onPointerDown={e => { if (zoom > 1) { (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); setDrag({ x: e.clientX, y: e.clientY, ox: offset.x, oy: offset.y }); } }} onPointerMove={e => { if (drag) setOffset({ x: drag.ox + e.clientX - drag.x, y: drag.oy + e.clientY - drag.y }); }} onPointerUp={() => setDrag(null)}>
            {selected?.is_model && !evidence.length ? <div className="model-card"><span className="model-icon">⌘</span><h3>Model fact</h3>{answer?.model_fact ? <dl><dt>Element</dt><dd>{answer.model_fact.element}{answer.model_fact.element_name ? ` · ${answer.model_fact.element_name}` : ''}</dd><dt>GlobalId</dt><dd>{answer.model_fact.guid || 'Model aggregate'}</dd><dt>Property</dt><dd>{answer.model_fact.property}: {String(answer.model_fact.value)}</dd></dl> : <p>This is a 3D building model. Ask a question to see the element, GlobalId and property used for the answer.</p>}</div> : selected && <div className="sheet-transform" style={{ transform: `translate(${offset.x}px,${offset.y}px) scale(${zoom})` }}><img ref={imageRef} className="sheet-image" src={imageUrl} onLoad={e => setRendered({ width: e.currentTarget.naturalWidth, height: e.currentTarget.naturalHeight })} alt="Selected architectural drawing" />
              {evidence.length > 0 && <svg className="evidence-layer" viewBox={`0 0 ${rendered.width} ${rendered.height}`} preserveAspectRatio="none">{evidence.map((ev, i) => ev.polygon?.length ? <g key={i}><polygon points={ev.polygon.map(([x,y]) => `${x * unitScaleX},${y * unitScaleY}`).join(' ')} /><text x={ev.bbox[0] * unitScaleX} y={Math.max(18, ev.bbox[1] * unitScaleY - 6)}>{ev.label || `Evidence ${i + 1}`}</text></g> : <g key={i}><rect x={ev.bbox[0] * unitScaleX} y={ev.bbox[1] * unitScaleY} width={(ev.bbox[2] - ev.bbox[0]) * unitScaleX} height={(ev.bbox[3] - ev.bbox[1]) * unitScaleY} /><text x={ev.bbox[0] * unitScaleX} y={Math.max(18, ev.bbox[1] * unitScaleY - 6)}>{ev.label || `Evidence ${i + 1}`}</text></g>)}</svg>}</div>}
          </div><div className="viewer-footer"><span><i className="dot-teal" /> {evidence.length ? `${evidence.length} evidence regions` : 'Evidence appears here after an answer'}</span><span>Drag to pan · Ctrl + scroll to zoom</span></div>
        </div>
        {evidence.length > 0 && <div className="evidence-strip"><span className="evidence-check">✓</span><span><b>{evidence.length} supporting region{evidence.length === 1 ? '' : 's'}</b><small>{evidence[0].label || 'Highlighted directly on the drawing'}</small></span><span className="source-file">{evidence[0].file.split('/').pop()}</span>{evidence[0].crop_url && <a className="source-file" href={evidence[0].highlight_url || evidence[0].crop_url} target="_blank" rel="noreferrer">Cloudinary overlay</a>}</div>}
      </section>
      <aside className="ask-column panel"><span className="eyebrow">ASK THIS DRAWING</span><h2>What do you want to know?</h2><label className="question-label" htmlFor="question">YOUR QUESTION</label><textarea id="question" value={question} onChange={e => setQuestion(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void ask(); } }} placeholder="e.g. How many doors are shown on this floor plan?" />
        <div className="examples-head"><span>TRY AN EXAMPLE</span><span>↘</span></div><div className="chips">{examples.map(q => <button key={q} onClick={() => setQuestion(q)}>{q}</button>)}</div>
        <button className="ask-button" onClick={() => void ask()} disabled={busy || !question.trim()}>{busy ? 'Analyzing drawing…' : 'Ask PlanSight'} <span>↗</span></button>
        {answer && <div className={`answer-card ${answer.abstained ? 'abstain' : ''}`}>{answer.abstained ? <><div className="answer-kicker">NOT CONFIDENT ENOUGH</div><h3>Couldn’t support an answer</h3><p>{answer.reason}</p></> : <><div className="answer-kicker">ANSWER <span className="method-badge">{answer.cached ? 'CACHED' : answer.method || 'deterministic'}</span></div><div className="answer-value">{String(answer.value)}<small>{answer.unit || ''}</small></div><div className="confidence-row"><span>Confidence</span><b>{Math.round((answer.confidence ?? 1) * 100)}%</b></div><div className="confidence-track"><i style={{ width: `${Math.round((answer.confidence ?? 1) * 100)}%` }} /></div><p className="explanation">{answer.explanation}</p><div className="solver-line">SOLVER <b>{answer.solver}</b></div></>}
          <div className="cost-box"><span className="eyebrow">COST & SPEED</span><b>This question <strong>${cost.toFixed(5)}</strong> <em>vs</em> naive frontier full-sheet <strong>${naive.toFixed(5)}</strong></b><div className="cost-foot"><span>{ratio}</span><span>{answer.latency_ms?.toFixed(0) ?? '—'} ms</span></div></div>
        </div>}
        <div className="privacy-note"><span>✦</span> Every answer is grounded in a drawing region you can inspect.</div>
      </aside>
    </div>
    <footer className="footer"><span>PLANSIGHT · JUNCTION 2026</span><span>Deterministic first · Evidence always visible</span></footer>
  </main>;
}

export default App;