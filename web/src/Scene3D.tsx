import { Suspense, useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { Html, OrbitControls, useGLTF } from '@react-three/drei';
import * as THREE from 'three';
import { sfx } from './sfx';

type Poly = [number, number][];
type Room = { id: string; polygon: Poly; name?: string | null; number?: string | null; area_m2?: number | null };
type PlanScene = { kind: 'plan'; raster?: { m_per_px: number; cx: number; cy: number } | null; bounds: [number, number, number, number]; walls: { id: string; polygon: Poly; holes?: Poly[]; height?: number }[]; rooms: Room[]; doors: { id: string; polygon: Poly }[]; windows: { id: string; polygon: Poly }[]; fixtures: { id: string; polygon: Poly }[]; unit_outlines?: { id: string; polygon: Poly }[] };
type IfcScene = { kind: 'ifc'; glb: string; elements: { guid: string; ifc_class: string; name?: string; storey?: string | null }[]; storeys?: { name: string; elevation: number }[] };
export type Highlight = { sceneKind?: string | null; roomNames?: string[]; ifcClass?: string | null; label?: string; expected?: number | null; boxes?: [number, number, number, number][] };
export type FlyRequest = { query: string; key: number } | null;
export type RoomInfo = { name: string; area_m2?: number | null };

const LIME = new THREE.Color('#1d4fd8'), CYAN = new THREE.Color('#0f766e');
const kindLabel: Record<string, string> = { doors: 'doors', windows: 'windows', rooms: 'rooms', units: 'apartments', fixtures: 'fixtures' };

// Spoken/typed words (EN/FI/DE/FR/SV) → the German room labels used on the Swiss plans.
const ROOM_WORDS: [RegExp, RegExp, string][] = [
  [/kitchen|keitti|küche|kuche|cuisine|kök/i, /küche|kuche/i, 'Kitchen'],
  [/bed|sleep|makuu|schlaf|chambre|sovrum|^rooms?$|zimmer/i, /zimmer/i, 'Bedrooms'],
  [/bath|wc|toilet|kylpy|vessa|bad|salle de bain|badrum/i, /^bad/i, 'Bathrooms'],
  [/living|dining|lounge|olohuone|wohn|séjour|vardags/i, /wohn/i, 'Living / dining'],
  [/corridor|hall|käytävä|eteinen|korridor|flur|couloir/i, /korridor/i, 'Corridors'],
  [/balcon|parveke|balkon/i, /balkon/i, 'Balconies'],
  [/storage|store|varasto|reduit|abstell/i, /reduit/i, 'Storage'],
  [/stair|porras|treppe|escalier/i, /treppe/i, 'Stairs'],
  [/lift|elevator|hissi|ascenseur|aufzug/i, /^lift/i, 'Lift'],
];
export function matchRooms(rooms: Room[], query: string): { label: string; rooms: Room[] } {
  const q = query.trim();
  for (const [word, label, nice] of ROOM_WORDS) if (word.test(q)) return { label: nice, rooms: rooms.filter(r => r.name && label.test(r.name)) };
  const direct = rooms.filter(r => r.name && (r.name.toLowerCase().includes(q.toLowerCase()) || (r.number && q.includes(r.number))));
  return { label: q, rooms: direct };
}

function shapeOf(poly: Poly, holes: Poly[] = []) {
  const s = new THREE.Shape(); poly.forEach(([x, y], i) => (i ? s.lineTo(x, y) : s.moveTo(x, y))); s.closePath();
  holes.forEach(h => { const p = new THREE.Path(); h.forEach(([x, y], i) => (i ? p.lineTo(x, y) : p.moveTo(x, y))); p.closePath(); s.holes.push(p); });
  return s;
}
const centroid = (p: Poly) => p.reduce((a, [x, y]) => [a[0] + x / p.length, a[1] + y / p.length], [0, 0]);
const ease = (p: number) => 1 - Math.pow(1 - Math.min(1, Math.max(0, p)), 3);

type OrbitLike = { target: THREE.Vector3; update: () => void; enabled: boolean };

/** Intro: straight above (looks like the sheet) → 3/4 view. Tour: glide from room to room. */
function CameraRig({ size, k, tour, ty = 0 }: { size: number; k: unknown; tour: { pts: [number, number][]; key: number } | null; ty?: number }) {
  const { camera, controls } = useThree() as unknown as { camera: THREE.PerspectiveCamera; controls: OrbitLike | null };
  const intro = useRef({ t0: performance.now(), done: false });
  const tr = useRef<{ t0: number; pts: [number, number][]; fromPos: THREE.Vector3; fromTgt: THREE.Vector3; idx: number; done: boolean } | null>(null);
  useEffect(() => { intro.current = { t0: performance.now(), done: false }; tr.current = null; }, [k]);
  useEffect(() => {
    if (!tour || !tour.pts.length) return;
    tr.current = { t0: performance.now(), pts: tour.pts, fromPos: camera.position.clone(), fromTgt: controls?.target.clone() || new THREE.Vector3(), idx: 0, done: false };
    intro.current.done = true;
  }, [tour?.key]); // eslint-disable-line react-hooks/exhaustive-deps
  useFrame(() => {
    if (!intro.current.done) {
      const e = ease((performance.now() - intro.current.t0) / 2600);
      camera.position.copy(new THREE.Vector3(0, size * 1.25, 0.001).lerp(new THREE.Vector3(size * 0.55, size * 0.62 + ty, size * 0.78), e));
      controls?.target.set(0, ty * e, 0); camera.lookAt(0, ty * e, 0); controls?.update();
      if (e >= 1) intro.current.done = true;
      return;
    }
    const t = tr.current; if (!t || t.done) return;
    const leg = 1700, hold = 1100, el = performance.now() - t.t0, i = Math.min(t.pts.length - 1, Math.floor(el / (leg + hold)));
    if (i !== t.idx) { t.fromPos = camera.position.clone(); t.fromTgt = controls?.target.clone() || new THREE.Vector3(); t.idx = i; sfx.tick(i + 3); }
    const local = el - i * (leg + hold), e = ease(local / leg);
    const [x, z] = t.pts[i], tgt = new THREE.Vector3(x, 0.4, z), pos = new THREE.Vector3(x + 5.5, 10.5, z + 8);
    camera.position.copy(t.fromPos.clone().lerp(pos, e)); controls?.target.copy(t.fromTgt.clone().lerp(tgt, e)); controls?.update();
    if (i === t.pts.length - 1 && local > leg) t.done = true;
  });
  return null;
}

function usePop(n: number, k: unknown, delay = 1500) {
  const [shown, setShown] = useState(0);
  useEffect(() => {
    setShown(0); if (!n) return; const step = Math.max(60, Math.min(380, 2200 / n)); let i = 0;
    let timer = setTimeout(function next() { i += 1; setShown(i); if (i < n) timer = setTimeout(next, step); }, delay);
    return () => clearTimeout(timer);
  }, [n, k, delay]);
  useEffect(() => { if (shown > 0) { sfx.tick(shown); if (shown === n) setTimeout(() => sfx.stamp(), 160); } }, [shown, n]);
  return shown;
}

function Extruded({ poly, holes, depth, z = 0, color, opacity = 1, emissive, lift }: { poly: Poly; holes?: Poly[]; depth: number; z?: number; color: string | THREE.Color; opacity?: number; emissive?: THREE.Color | null; lift: React.MutableRefObject<number> }) {
  const geo = useMemo(() => new THREE.ExtrudeGeometry(shapeOf(poly, holes), { depth, bevelEnabled: false }), [poly, holes, depth]);
  const ref = useRef<THREE.Mesh>(null);
  useFrame(() => { if (ref.current) { ref.current.scale.z = Math.max(0.001, lift.current); ref.current.position.z = z * lift.current; } });
  return <mesh ref={ref} geometry={geo} castShadow receiveShadow>
    <meshStandardMaterial color={color} transparent={opacity < 1} opacity={opacity} emissive={emissive || '#000'} emissiveIntensity={emissive ? 1.4 : 0} roughness={.55} metalness={.05} />
  </mesh>;
}

function PlanModel({ scene, hl, k, focus, onCount }: { scene: PlanScene; hl: Highlight; k: unknown; focus: Room[]; onCount: (shown: number, total: number) => void }) {
  const lift = useRef(0.001); const t0 = useRef(performance.now());
  useEffect(() => { t0.current = performance.now(); lift.current = 0.001; }, [k]);
  useFrame(() => { lift.current = ease((performance.now() - t0.current - 500) / 1600); });
  const [cx, cy] = [(scene.bounds[0] + scene.bounds[2]) / 2, (scene.bounds[1] + scene.bounds[3]) / 2];
  const kind = focus.length ? '' : hl.sceneKind || '';
  const targets = useMemo(() => {
    type T = Room & { ids: string[] };
    let list: Room[] = [];
    if (scene.raster && hl.boxes?.length) {
      const { m_per_px: m, cx: rx, cy: ry } = scene.raster;
      const toM = (x: number, y: number): [number, number] => [(x - rx) * m, -(y - ry) * m];
      list = hl.boxes.map(([x0, y0, x1, y1], i) => ({ id: `b${i}`, polygon: [toM(x0, y0), toM(x1, y0), toM(x1, y1), toM(x0, y1)] }));
      return list.map(it => ({ ...it, ids: [it.id] })).sort((a, b) => centroid(a.polygon)[0] - centroid(b.polygon)[0]);
    }
    if (kind === 'doors') list = scene.doors; else if (kind === 'windows') list = scene.windows; else if (kind === 'fixtures') list = scene.fixtures;
    else if (kind === 'units') list = scene.unit_outlines || [];
    else if (kind === 'rooms') { const names = (hl.roomNames || []).map(n => n.toLowerCase()); list = names.length ? scene.rooms.filter(r => r.name && names.some(n => r.name!.toLowerCase().includes(n) || n.includes(r.name!.toLowerCase()))) : scene.rooms; }
    const merge = kind === 'doors' || kind === 'windows' || kind === 'fixtures';
    // CAD draws one door as several parts (leaf + swing): merge nearby parts, using the smallest radius that matches the verified count.
    const group = (r: number) => { const out: T[] = []; for (const it of list) { const c = centroid(it.polygon); const g = r > 0 ? out.find(g => { const d = centroid(g.polygon); return Math.hypot(c[0] - d[0], c[1] - d[1]) < r; }) : undefined; if (g) g.ids.push(it.id); else out.push({ ...it, ids: [it.id] }); } return out; };
    let groups = group(0);
    if (merge && hl.expected && list.length > hl.expected) {
      let best = groups;
      for (let r = 0.1; r <= 1.5; r += 0.05) { const g = group(r); if (Math.abs(g.length - hl.expected) < Math.abs(best.length - hl.expected)) best = g; if (g.length === hl.expected) break; }
      groups = best;
    }
    return groups.sort((a, b) => centroid(a.polygon)[0] - centroid(b.polygon)[0]);
  }, [scene, kind, hl.roomNames, hl.expected, hl.boxes]);
  const shown = usePop(targets.length, k, 2300);
  useEffect(() => onCount(shown, targets.length), [shown, targets.length]); // eslint-disable-line react-hooks/exhaustive-deps
  const lit = new Set(targets.slice(0, shown).flatMap(t => t.ids));
  const focusIds = new Set(focus.map(r => r.id));
  const dim = targets.length > 0 || focus.length > 0;
  const tagRooms = focus.length ? focus : (kind === 'rooms' || kind === 'units') ? targets.slice(0, shown) : [];
  return <group rotation={[-Math.PI / 2, 0, 0]} position={[-cx, 0, cy]}>
    {scene.rooms.map(r => { const on = lit.has(r.id) || focusIds.has(r.id); const col = focusIds.has(r.id) ? CYAN : LIME; return <Extruded key={r.id} poly={r.polygon} depth={on ? 0.12 : 0.04} color={on ? col : '#e4ded0'} emissive={on ? col : null} opacity={on ? .6 : 1} lift={lift} />; })}
    {kind === 'units' && targets.map(u => <Extruded key={u.id} poly={u.polygon} depth={0.06} z={0.02} color={lit.has(u.id) ? LIME : '#e4ded0'} emissive={lit.has(u.id) ? LIME : null} opacity={.35} lift={lift} />)}
    {scene.walls.map(w => <Extruded key={w.id} poly={w.polygon} holes={w.holes} depth={w.height || 2.7} color="#2a2d33" opacity={dim ? .45 : .96} lift={lift} />)}
    {scene.raster && targets.map(t => { const on = lit.has(t.id); const win = kind === 'windows'; return <Extruded key={t.id} poly={t.polygon} depth={win ? 1.3 : kind === 'doors' ? 2.1 : 1} z={win ? .9 : 0} color={on ? LIME : '#a9a294'} emissive={on ? LIME : null} opacity={on ? 1 : .4} lift={lift} />; })}
    {scene.raster && <Extruded poly={[[scene.bounds[0] - .3, scene.bounds[1] - .3], [scene.bounds[2] + .3, scene.bounds[1] - .3], [scene.bounds[2] + .3, scene.bounds[3] + .3], [scene.bounds[0] - .3, scene.bounds[3] + .3]]} depth={0.02} color="#d8d1c2" lift={lift} />}
    {scene.doors.map(d => <Extruded key={d.id} poly={d.polygon} depth={lit.has(d.id) ? 2.1 : .05} color={lit.has(d.id) ? LIME : '#8a8478'} emissive={lit.has(d.id) ? LIME : null} lift={lift} />)}
    {scene.windows.map(w => <Extruded key={w.id} poly={w.polygon} depth={1.3} z={.9} color={lit.has(w.id) ? LIME : CYAN} emissive={lit.has(w.id) ? LIME : null} opacity={lit.has(w.id) ? 1 : .35} lift={lift} />)}
    {scene.fixtures.map(f => <Extruded key={f.id} poly={f.polygon} depth={lit.has(f.id) ? .9 : .45} color={lit.has(f.id) ? LIME : '#bdb6a6'} emissive={lit.has(f.id) ? LIME : null} lift={lift} />)}
    {tagRooms.filter(t => t.name || kind === 'units').slice(0, 14).map((t, i) => { const [x, y] = centroid(t.polygon); return <Html key={t.id} position={[x, y, 3]} center distanceFactor={focus.length ? 13 : 18} zIndexRange={[5, 0]}><div className={`tag3d ${focus.length ? 'cyan' : ''}`}>{kind === 'units' ? `apartment ${i + 1}` : t.name}{t.number ? <small>{t.number}{t.area_m2 ? ` · ${t.area_m2} m²` : ''}</small> : t.area_m2 ? <small>{t.area_m2} m²</small> : null}</div></Html>; })}
  </group>;
}

function IfcModel({ scene, hl, k, onCount }: { scene: IfcScene; hl: Highlight; k: unknown; onCount: (shown: number, total: number) => void }) {
  const gltf = useGLTF(scene.glb);
  const root = useMemo(() => gltf.scene.clone(true), [gltf]);
  const storeyOf = useMemo(() => new Map(scene.elements.map(e => [e.guid, e.storey ?? null])), [scene]);
  const storeyIdx = useMemo(() => new Map((scene.storeys || []).map((s, i) => [s.name, i])), [scene]);
  const meshes = useMemo(() => {
    const out: { mesh: THREE.Mesh; cls: string; storey: string | null; orig: number }[] = [];
    root.traverse(o => { if ((o as THREE.Mesh).isMesh) { const name = o.name || o.parent?.name || ''; const cut = name.indexOf('_'); const cls = name.slice(0, cut).replace(/\d+$/, ''); const guid = name.slice(cut + 1); out.push({ mesh: o as THREE.Mesh, cls, storey: storeyOf.get(guid) ?? storeyOf.get(o.parent?.name.slice(o.parent.name.indexOf('_') + 1) || '') ?? null, orig: o.position.z }); } });
    return out;
  }, [root, storeyOf]);
  const cls = hl.ifcClass || '';
  const targets = useMemo(() => meshes.filter(m => cls && m.cls.toLowerCase() === cls.toLowerCase()).sort((a, b) => (storeyIdx.get(a.storey || '') ?? 0) - (storeyIdx.get(b.storey || '') ?? 0) || new THREE.Box3().setFromObject(a.mesh).min.x - new THREE.Box3().setFromObject(b.mesh).min.x), [meshes, cls, storeyIdx]);
  const shown = usePop(targets.length, k, 2300);
  useEffect(() => onCount(shown, targets.length), [shown, targets.length]); // eslint-disable-line react-hooks/exhaustive-deps
  const mats = useMemo(() => ({
    base: new THREE.MeshStandardMaterial({ color: '#d7e1ea', roughness: .6, metalness: .05 }),
    ghost: new THREE.MeshStandardMaterial({ color: '#8fb4d6', transparent: true, opacity: .09, depthWrite: false }),
    lit: new THREE.MeshStandardMaterial({ color: LIME, emissive: LIME, emissiveIntensity: 1.3, roughness: .4 }),
    pending: new THREE.MeshStandardMaterial({ color: '#a9a294', transparent: true, opacity: .5 }),
  }), []);
  const litSet = new Set(targets.slice(0, shown).map(t => t.mesh));
  const targetSet = new Set(targets.map(t => t.mesh));
  meshes.forEach(({ mesh, cls: c }) => {
    mesh.visible = c !== 'IfcSpace' || targetSet.has(mesh);
    mesh.material = litSet.has(mesh) ? mats.lit : targetSet.has(mesh) ? mats.pending : targets.length ? mats.ghost : mats.base;
  });
  const box = useMemo(() => new THREE.Box3().setFromObject(root), [root]);
  const c = box.getCenter(new THREE.Vector3());
  // Exploded view: once every target is counted, floors separate so per-floor counts are visible.
  const allLit = targets.length > 0 && shown >= targets.length;
  const explodeT0 = useRef<number | null>(null); const [exploded, setExploded] = useState(false);
  useEffect(() => { explodeT0.current = null; setExploded(false); }, [k, cls]);
  useEffect(() => { if (allLit && explodeT0.current === null) { const t = setTimeout(() => { explodeT0.current = performance.now(); sfx.split(); }, 700); return () => clearTimeout(t); } }, [allLit]);
  const GAP = 3;
  const lift = useRef<THREE.Group>(null); const t0 = useRef(performance.now());
  useEffect(() => { t0.current = performance.now(); }, [k]);
  useFrame(() => {
    if (lift.current) lift.current.scale.y = Math.max(.001, ease((performance.now() - t0.current - 400) / 1600));
    const e = explodeT0.current === null ? 0 : ease((performance.now() - explodeT0.current) / 1300);
    meshes.forEach(m => { m.mesh.position.z = m.orig + (storeyIdx.get(m.storey || '') ?? 0) * GAP * e; });
    if (e >= 1 && !exploded) setExploded(true);
  });
  const perStorey = useMemo(() => { const m = new Map<string, number>(); targets.forEach(t => m.set(t.storey || '?', (m.get(t.storey || '?') || 0) + 1)); return m; }, [targets]);
  const elev = (v: number) => Math.abs(v) > 100 ? v / 1000 : v;
  const what = cls.replace(/^Ifc/, '').toLowerCase();
  return <group ref={lift}><group rotation={[-Math.PI / 2, 0, 0]}>
    <primitive object={root} position={[-c.x, -c.y, -box.min.z]} />
    {exploded && (scene.storeys || []).map((s, i) => perStorey.get(s.name) ? <Html key={s.name} zIndexRange={[5, 0]} position={[box.max.x - c.x + 1.2, 0, elev(s.elevation) - box.min.z + i * GAP + 1.4]} center={false}><div className="storey-tag" style={{ animationDelay: `${i * 0.12}s` }}>floor {s.name}<b>{perStorey.get(s.name)}</b> {what}s</div></Html> : null)}
  </group></group>;
}

export default function Scene3D({ path, hl, k, fly, onRooms }: { path: string; hl: Highlight; k: unknown; fly?: FlyRequest; onRooms?: (rooms: RoomInfo[]) => void }) {
  const [scene, setScene] = useState<PlanScene | IfcScene | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [count, setCount] = useState<[number, number]>([0, 0]);
  const [focus, setFocus] = useState<{ label: string; rooms: Room[]; key: number } | null>(null);
  useEffect(() => { setScene(null); setErr(null); setFocus(null); fetch(`/api/scene3d?path=${encodeURIComponent(path)}`).then(r => r.ok ? r.json() : Promise.reject(r.status)).then(setScene).catch(() => setErr('No 3D source for this drawing.')); }, [path]);
  useEffect(() => { setFocus(null); }, [k]);
  useEffect(() => { if (scene?.kind === 'plan') onRooms?.(scene.rooms.filter(r => r.name).map(r => ({ name: r.name!, area_m2: r.area_m2 }))); }, [scene]); // eslint-disable-line react-hooks/exhaustive-deps
  const tourTo = (query: string) => { if (scene?.kind !== 'plan') return; const m = matchRooms(scene.rooms, query); if (m.rooms.length) { sfx.whoosh(); setFocus({ ...m, key: Date.now() }); } };
  useEffect(() => { if (fly && scene?.kind === 'plan') tourTo(fly.query); }, [fly?.key, scene]); // eslint-disable-line react-hooks/exhaustive-deps
  const size = scene?.kind === 'plan' ? Math.max(scene.bounds[2] - scene.bounds[0], scene.bounds[3] - scene.bounds[1]) : 34;
  const what = scene?.kind === 'ifc' ? (hl.ifcClass ? hl.ifcClass.replace(/^Ifc/, '') + 's' : '') : kindLabel[hl.sceneKind || ''] || '';
  const tour = useMemo(() => {
    if (!focus || scene?.kind !== 'plan') return null;
    const [cx, cy] = [(scene.bounds[0] + scene.bounds[2]) / 2, (scene.bounds[1] + scene.bounds[3]) / 2];
    return { pts: focus.rooms.slice(0, 8).map(r => { const [x, y] = centroid(r.polygon); return [x - cx, -y + cy] as [number, number]; }), key: focus.key };
  }, [focus, scene]);
  const chips = useMemo(() => scene?.kind === 'plan' ? ROOM_WORDS.map(([, label, nice]) => ({ nice, n: scene.rooms.filter(r => r.name && label.test(r.name)).length })).filter(c => c.n > 0) : [], [scene]);
  return <div className="scene3d">
    {err && <div className="scene-msg">{err}</div>}
    {!scene && !err && <div className="scene-msg">Building 3D from the {path.includes('ifc') ? 'IFC model' : 'CAD layers'}…</div>}
    {scene && <Canvas shadows dpr={[1, 2]} camera={{ fov: 40, near: .1, far: 1000, position: [0, size * 1.25, .001] }}>
      <color attach="background" args={['#efebe2']} />
      <fog attach="fog" args={['#efebe2', size * 1.6, size * 4.5]} />
      <ambientLight intensity={.55} />
      <directionalLight position={[size * .6, size, size * .4]} intensity={1.6} castShadow shadow-mapSize={[2048, 2048]} />
      <directionalLight position={[-size, size * .5, -size * .6]} intensity={.4} color="#ffffff" />
      <gridHelper args={[size * 3, Math.round(size * 3), '#cfc8b8', '#e0dacd']} position={[0, -0.01, 0]} />
      <Suspense fallback={null}>
        {scene.kind === 'plan' ? <PlanModel scene={scene} hl={hl} k={`${k}-${path}`} focus={focus?.rooms || []} onCount={(a, b) => setCount([a, b])} /> : <IfcModel scene={scene} hl={hl} k={`${k}-${path}`} onCount={(a, b) => setCount([a, b])} />}
      </Suspense>
      <OrbitControls makeDefault enableDamping maxPolarAngle={Math.PI / 2.05} />
      <CameraRig size={size} k={`${k}-${path}`} tour={tour} ty={scene.kind === 'ifc' ? 7 : 0} />
    </Canvas>}
    {focus ? <div className="stage-counter scene-counter cyan"><span>{focus.label} · fly-through</span><b className="done">{focus.rooms.length}</b></div>
      : count[1] > 0 && <div className="stage-counter scene-counter"><span>{what || 'items'} · 3D</span><b className={count[0] >= count[1] ? 'done' : ''}>{hl.expected != null && scene?.kind === 'plan' ? Math.round(hl.expected * count[0] / count[1]) : count[0]}</b></div>}
    {chips.length > 0 && <div className="tour-chips"><span>Fly to</span>{chips.map(c => <button key={c.nice} className={focus?.label === c.nice ? 'on' : ''} onClick={() => tourTo(c.nice)}>{c.nice} <i>{c.n}</i></button>)}</div>}
    <div className="scene-hint">{scene?.kind === 'ifc' ? 'IFC model · every element is a real BIM object' : scene && 'raster' in scene && scene.raster ? 'Walls traced from the image (OpenCV) · objects from the detector boxes' : 'Extruded from the DXF wall, door and window layers'} · drag to orbit · scroll to zoom</div>
  </div>;
}
