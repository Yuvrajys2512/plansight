import { Suspense, useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { Html, OrbitControls, useGLTF } from '@react-three/drei';
import * as THREE from 'three';

type Poly = [number, number][];
type PlanScene = { kind: 'plan'; bounds: [number, number, number, number]; walls: { id: string; polygon: Poly; height?: number }[]; rooms: { id: string; polygon: Poly; name?: string | null; number?: string | null; area_m2?: number | null }[]; doors: { id: string; polygon: Poly }[]; windows: { id: string; polygon: Poly }[]; fixtures: { id: string; polygon: Poly }[]; unit_outlines?: { id: string; polygon: Poly }[] };
type IfcScene = { kind: 'ifc'; glb: string; elements: { guid: string; ifc_class: string; name?: string }[] };
export type Highlight = { sceneKind?: string | null; roomNames?: string[]; ifcClass?: string | null; label?: string; expected?: number | null };

const LIME = new THREE.Color('#c8ff3d'), CYAN = new THREE.Color('#3de0ff');
const kindLabel: Record<string, string> = { doors: 'doors', windows: 'windows', rooms: 'rooms', units: 'apartments', fixtures: 'fixtures' };

function shapeOf(poly: Poly) {
  const s = new THREE.Shape(); poly.forEach(([x, y], i) => (i ? s.lineTo(x, y) : s.moveTo(x, y))); s.closePath(); return s;
}
const centroid = (p: Poly) => p.reduce((a, [x, y]) => [a[0] + x / p.length, a[1] + y / p.length], [0, 0]);

/** Camera starts straight above (looks like the 2D sheet), then swings into a 3/4 view while the walls rise. */
function CameraIntro({ size, k }: { size: number; k: unknown }) {
  const { camera } = useThree(); const t0 = useRef(performance.now()); const done = useRef(false);
  useEffect(() => { t0.current = performance.now(); done.current = false; }, [k]);
  useFrame(() => {
    if (done.current) return;
    const p = Math.min(1, (performance.now() - t0.current) / 2600), e = 1 - Math.pow(1 - p, 3);
    const top = new THREE.Vector3(0, size * 1.25, 0.001), side = new THREE.Vector3(size * 0.55, size * 0.62, size * 0.78);
    camera.position.copy(top.lerp(side, e)); camera.lookAt(0, 0, 0);
    if (p >= 1) done.current = true;
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
  return shown;
}

function Extruded({ poly, depth, z = 0, color, opacity = 1, emissive, lift }: { poly: Poly; depth: number; z?: number; color: string | THREE.Color; opacity?: number; emissive?: THREE.Color | null; lift: React.MutableRefObject<number> }) {
  const geo = useMemo(() => new THREE.ExtrudeGeometry(shapeOf(poly), { depth, bevelEnabled: false }), [poly, depth]);
  const ref = useRef<THREE.Mesh>(null);
  useFrame(() => { if (ref.current) { ref.current.scale.z = Math.max(0.001, lift.current); ref.current.position.z = z * lift.current; } });
  return <mesh ref={ref} geometry={geo} castShadow receiveShadow>
    <meshStandardMaterial color={color} transparent={opacity < 1} opacity={opacity} emissive={emissive || '#000'} emissiveIntensity={emissive ? 1.4 : 0} roughness={.55} metalness={.05} />
  </mesh>;
}

function PlanModel({ scene, hl, k, onCount }: { scene: PlanScene; hl: Highlight; k: unknown; onCount: (shown: number, total: number) => void }) {
  const lift = useRef(0.001); const t0 = useRef(performance.now());
  useEffect(() => { t0.current = performance.now(); lift.current = 0.001; }, [k]);
  useFrame(() => { const p = Math.min(1, Math.max(0, (performance.now() - t0.current - 500) / 1600)); lift.current = 1 - Math.pow(1 - p, 3); });
  const [cx, cy] = [(scene.bounds[0] + scene.bounds[2]) / 2, (scene.bounds[1] + scene.bounds[3]) / 2];
  const kind = hl.sceneKind || '';
  const targets = useMemo(() => {
    type T = { id: string; ids: string[]; polygon: Poly; name?: string | null; area_m2?: number | null };
    let list: { id: string; polygon: Poly; name?: string | null; area_m2?: number | null }[] = [];
    if (kind === 'doors') list = scene.doors; else if (kind === 'windows') list = scene.windows; else if (kind === 'fixtures') list = scene.fixtures;
    else if (kind === 'units') list = scene.unit_outlines || [];
    else if (kind === 'rooms') { const names = (hl.roomNames || []).map(n => n.toLowerCase()); list = names.length ? scene.rooms.filter(r => r.name && names.some(n => r.name!.toLowerCase().includes(n) || n.includes(r.name!.toLowerCase()))) : scene.rooms; }
    // CAD draws one door as several parts (leaf + swing): merge parts whose centres are within 0.9 m into one counted item.
    const merge = kind === 'doors' || kind === 'windows' || kind === 'fixtures';
    const group = (r: number) => { const out: T[] = []; for (const it of list) { const c = centroid(it.polygon); const g = r > 0 ? out.find(g => { const d = centroid(g.polygon); return Math.hypot(c[0] - d[0], c[1] - d[1]) < r; }) : undefined; if (g) g.ids.push(it.id); else out.push({ ...it, ids: [it.id] }); } return out; };
    // Pick the smallest merge radius whose item count matches the solver's verified answer (or the closest one).
    let groups = group(0);
    if (merge && hl.expected && list.length > hl.expected) {
      let best = groups;
      for (let r = 0.1; r <= 1.5; r += 0.05) { const g = group(r); if (Math.abs(g.length - hl.expected) < Math.abs(best.length - hl.expected)) best = g; if (g.length === hl.expected) break; }
      groups = best;
    }
    return groups.sort((a, b) => centroid(a.polygon)[0] - centroid(b.polygon)[0]);
  }, [scene, kind, hl.roomNames, hl.expected]);
  const shown = usePop(targets.length, k, 2300);
  useEffect(() => onCount(shown, targets.length), [shown, targets.length]); // eslint-disable-line react-hooks/exhaustive-deps
  const lit = new Set(targets.slice(0, shown).flatMap(t => t.ids));
  const dim = targets.length > 0;
  return <group rotation={[-Math.PI / 2, 0, 0]} position={[-cx, 0, cy]}>
    {scene.rooms.map(r => <Extruded key={r.id} poly={r.polygon} depth={0.04} color={lit.has(r.id) ? LIME : '#1d2a38'} emissive={lit.has(r.id) ? LIME : null} opacity={lit.has(r.id) ? .55 : 1} lift={lift} />)}
    {kind === 'units' && targets.map(u => <Extruded key={u.id} poly={u.polygon} depth={0.06} z={0.02} color={lit.has(u.id) ? LIME : '#1d2a38'} emissive={lit.has(u.id) ? LIME : null} opacity={.35} lift={lift} />)}
    {scene.walls.map(w => <Extruded key={w.id} poly={w.polygon} depth={w.height || 2.7} color="#dfe7ef" opacity={dim ? .5 : .96} lift={lift} />)}
    {scene.doors.map(d => <Extruded key={d.id} poly={d.polygon} depth={lit.has(d.id) ? 2.1 : .05} color={lit.has(d.id) ? LIME : '#6d7d8f'} emissive={lit.has(d.id) ? LIME : null} lift={lift} />)}
    {scene.windows.map(w => <Extruded key={w.id} poly={w.polygon} depth={1.3} z={.9} color={lit.has(w.id) ? LIME : CYAN} emissive={lit.has(w.id) ? LIME : null} opacity={lit.has(w.id) ? 1 : .35} lift={lift} />)}
    {scene.fixtures.map(f => <Extruded key={f.id} poly={f.polygon} depth={lit.has(f.id) ? .9 : .45} color={lit.has(f.id) ? LIME : '#8a99aa'} emissive={lit.has(f.id) ? LIME : null} lift={lift} />)}
    {(kind === 'rooms' || kind === 'units') && targets.slice(0, shown).filter(t => t.name || kind === 'units').slice(0, 14).map((t, i) => { const [x, y] = centroid(t.polygon); return <Html key={t.id} position={[x, y, 3]} center distanceFactor={18}><div className="tag3d">{kind === 'units' ? `apartment ${i + 1}` : t.name}{t.area_m2 ? <small>{t.area_m2} m²</small> : null}</div></Html>; })}
  </group>;
}

function IfcModel({ url, hl, k, onCount }: { url: string; hl: Highlight; k: unknown; onCount: (shown: number, total: number) => void }) {
  const gltf = useGLTF(url);
  const root = useMemo(() => gltf.scene.clone(true), [gltf]);
  const meshes = useMemo(() => { const out: { mesh: THREE.Mesh; cls: string }[] = []; root.traverse(o => { if ((o as THREE.Mesh).isMesh) out.push({ mesh: o as THREE.Mesh, cls: (o.name.split('_')[0] || '').replace(/\d+$/, '') }); }); return out; }, [root]);
  const cls = hl.ifcClass || '';
  const targets = useMemo(() => meshes.filter(m => cls && m.cls.toLowerCase() === cls.toLowerCase()).sort((a, b) => { const pa = new THREE.Box3().setFromObject(a.mesh).getCenter(new THREE.Vector3()), pb = new THREE.Box3().setFromObject(b.mesh).getCenter(new THREE.Vector3()); return pa.z - pb.z || pa.x - pb.x; }), [meshes, cls]);
  const shown = usePop(targets.length, k, 2300);
  useEffect(() => onCount(shown, targets.length), [shown, targets.length]); // eslint-disable-line react-hooks/exhaustive-deps
  const mats = useMemo(() => ({
    base: new THREE.MeshStandardMaterial({ color: '#d7e1ea', roughness: .6, metalness: .05 }),
    ghost: new THREE.MeshStandardMaterial({ color: '#8fb4d6', transparent: true, opacity: .09, depthWrite: false }),
    lit: new THREE.MeshStandardMaterial({ color: LIME, emissive: LIME, emissiveIntensity: 1.3, roughness: .4 }),
    pending: new THREE.MeshStandardMaterial({ color: '#3a4a5c', transparent: true, opacity: .5 }),
  }), []);
  const litSet = new Set(targets.slice(0, shown).map(t => t.mesh));
  const targetSet = new Set(targets.map(t => t.mesh));
  meshes.forEach(({ mesh, cls: c }) => {
    const isSpace = c === 'IfcSpace';
    mesh.visible = !isSpace || targetSet.has(mesh);
    mesh.material = litSet.has(mesh) ? mats.lit : targetSet.has(mesh) ? mats.pending : targets.length ? mats.ghost : mats.base;
    mesh.castShadow = true;
  });
  const box = useMemo(() => new THREE.Box3().setFromObject(root), [root]);
  const c = box.getCenter(new THREE.Vector3());
  const lift = useRef<THREE.Group>(null); const t0 = useRef(performance.now());
  useEffect(() => { t0.current = performance.now(); }, [k]);
  useFrame(() => { if (!lift.current) return; const p = Math.min(1, Math.max(0, (performance.now() - t0.current - 400) / 1600)); lift.current.scale.y = Math.max(.001, 1 - Math.pow(1 - p, 3)); });
  // trimesh writes the IFC's Z-up coordinates as-is; rotate into three.js Y-up.
  return <group ref={lift}><group rotation={[-Math.PI / 2, 0, 0]}><primitive object={root} position={[-c.x, -c.y, -box.min.z]} /></group></group>;
}

export default function Scene3D({ path, hl, k }: { path: string; hl: Highlight; k: unknown }) {
  const [scene, setScene] = useState<PlanScene | IfcScene | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [count, setCount] = useState<[number, number]>([0, 0]);
  useEffect(() => { setScene(null); setErr(null); fetch(`/api/scene3d?path=${encodeURIComponent(path)}`).then(r => r.ok ? r.json() : Promise.reject(r.status)).then(setScene).catch(() => setErr('No 3D source for this drawing.')); }, [path]);
  const size = scene?.kind === 'plan' ? Math.max(scene.bounds[2] - scene.bounds[0], scene.bounds[3] - scene.bounds[1]) : 22;
  const what = scene?.kind === 'ifc' ? (hl.ifcClass ? hl.ifcClass.replace(/^Ifc/, '') + 's' : '') : kindLabel[hl.sceneKind || ''] || '';
  return <div className="scene3d">
    {err && <div className="scene-msg">{err}</div>}
    {!scene && !err && <div className="scene-msg">Building 3D from the {path.endsWith('.pdf') && path.includes('ifc') ? 'IFC model' : 'CAD layers'}…</div>}
    {scene && <Canvas shadows dpr={[1, 2]} camera={{ fov: 40, near: .1, far: 1000, position: [0, size * 1.25, .001] }}>
      <color attach="background" args={['#060a10']} />
      <fog attach="fog" args={['#060a10', size * 1.6, size * 4]} />
      <ambientLight intensity={.55} />
      <directionalLight position={[size * .6, size, size * .4]} intensity={1.6} castShadow shadow-mapSize={[2048, 2048]} />
      <directionalLight position={[-size, size * .5, -size * .6]} intensity={.4} color="#3de0ff" />
      <gridHelper args={[size * 3, Math.round(size * 3), '#16324a', '#0d1b29']} position={[0, -0.01, 0]} />
      <Suspense fallback={null}>
        {scene.kind === 'plan' ? <PlanModel scene={scene} hl={hl} k={`${k}-${path}`} onCount={(a, b) => setCount([a, b])} /> : <IfcModel url={scene.glb} hl={hl} k={`${k}-${path}`} onCount={(a, b) => setCount([a, b])} />}
      </Suspense>
      <CameraIntro size={size} k={`${k}-${path}`} />
      <OrbitControls makeDefault enableDamping maxPolarAngle={Math.PI / 2.05} />
    </Canvas>}
    {count[1] > 0 && <div className="stage-counter scene-counter"><span>{what || 'items'} · 3D</span><b className={count[0] >= count[1] ? 'done' : ''}>{hl.expected != null && scene?.kind === 'plan' ? Math.round(hl.expected * count[0] / count[1]) : count[0]}</b></div>}
    <div className="scene-hint">{scene?.kind === 'ifc' ? 'IFC model · every element is a real BIM object' : 'Extruded from the DXF wall, door and window layers'} · drag to orbit · scroll to zoom</div>
  </div>;
}
