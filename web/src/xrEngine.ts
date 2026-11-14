// Live camera AR (WebXR immersive-ar): find the table with hit-test, tap to place, the building constructs itself
// on the table, and answers light up their evidence in place. Plain three.js so we control the XR frame loop.
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

type Poly = [number, number][];
type PlanScene = { kind: 'plan'; raster?: { m_per_px: number; cx: number; cy: number } | null; bounds: [number, number, number, number]; walls: { id: string; polygon: Poly; holes?: Poly[]; height?: number }[]; rooms: { id: string; polygon: Poly; name?: string | null }[]; doors: { id: string; polygon: Poly }[]; windows: { id: string; polygon: Poly }[]; fixtures: { id: string; polygon: Poly }[]; unit_outlines?: { id: string; polygon: Poly }[] };
type IfcScene = { kind: 'ifc'; glb: string; storeys?: { name: string; elevation: number }[]; elements: { guid: string; ifc_class: string; storey?: string | null }[] };
export type XrAnswer = { value?: unknown; evidence?: { bbox: [number, number, number, number] }[]; scene_kind?: string | null; scene_room_names?: string[]; explanation?: string; model_fact?: { element?: string } | null; abstained?: boolean };

const TABLE = 0.45, VEX = 1.8;
const LIME = new THREE.Color('#c8ff3d');
const ease = (p: number) => 1 - Math.pow(1 - Math.min(1, Math.max(0, p)), 3);
const centroid = (p: Poly) => p.reduce((a, [x, y]) => [a[0] + x / p.length, a[1] + y / p.length], [0, 0]);

function prism(poly: Poly, depth: number, holes: Poly[] = []) {
  const s = new THREE.Shape(); poly.forEach(([x, y], i) => (i ? s.lineTo(x, y) : s.moveTo(x, y))); s.closePath();
  holes.forEach(h => { const p = new THREE.Path(); h.forEach(([x, y], i) => (i ? p.lineTo(x, y) : p.moveTo(x, y))); p.closePath(); s.holes.push(p); });
  const g = new THREE.ExtrudeGeometry(s, { depth, bevelEnabled: false });
  g.rotateX(-Math.PI / 2);   // shape XY → ground plane, extrusion → up
  return g;
}

type Anim = { obj: THREE.Object3D; t0: number; dur: number; kind: 'grow' | 'pop' | 'show' };

export class ArEngine {
  renderer: THREE.WebGLRenderer; scene = new THREE.Scene(); camera = new THREE.PerspectiveCamera(70, 1, 0.01, 40);
  reticle: THREE.Mesh; anchor = new THREE.Group(); model = new THREE.Group(); hl = new THREE.Group();
  session: XRSession | null = null; hitSource: XRHitTestSource | null = null; refSpace: XRReferenceSpace | null = null;
  placed = false; anims: Anim[] = []; data: PlanScene | IfcScene | null = null; ifcMeshes: { mesh: THREE.Mesh; cls: string; storey: string | null }[] = [];
  mats = { wall: new THREE.MeshStandardMaterial({ color: '#e6edf3', roughness: .7 }), floor: new THREE.MeshStandardMaterial({ color: '#1d2a38', roughness: .9 }),
    room: new THREE.MeshStandardMaterial({ color: '#2b3d52', roughness: .9 }), door: new THREE.MeshStandardMaterial({ color: '#6d7d8f' }),
    glass: new THREE.MeshStandardMaterial({ color: '#3de0ff', transparent: true, opacity: .45 }), lit: new THREE.MeshStandardMaterial({ color: LIME, emissive: LIME, emissiveIntensity: .9, roughness: .4 }),
    ghost: new THREE.MeshStandardMaterial({ color: '#9fc3e6', transparent: true, opacity: .16, depthWrite: false }), pending: new THREE.MeshStandardMaterial({ color: '#3a4a5c', transparent: true, opacity: .55 }) };
  onPlaced?: () => void; onCount?: (shown: number, total: number) => void; onTick?: (i: number) => void; onDone?: () => void; onEnd?: () => void;

  constructor() {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(window.devicePixelRatio); this.renderer.setSize(window.innerWidth, window.innerHeight);
    this.renderer.xr.enabled = true; this.renderer.shadowMap.enabled = true;
    this.renderer.domElement.style.cssText = 'position:fixed;inset:0;z-index:0';
    this.scene.add(new THREE.HemisphereLight('#ffffff', '#445566', 1.6));
    const sun = new THREE.DirectionalLight('#ffffff', 1.6); sun.position.set(.4, 1.2, .3); sun.castShadow = true;
    sun.shadow.mapSize.set(1024, 1024); Object.assign(sun.shadow.camera, { left: -.5, right: .5, top: .5, bottom: -.5, near: .01, far: 3 });
    this.anchor.add(sun); this.anchor.add(sun.target);
    const catcher = new THREE.Mesh(new THREE.PlaneGeometry(1.4, 1.4).rotateX(-Math.PI / 2), new THREE.ShadowMaterial({ opacity: .35 }));
    catcher.receiveShadow = true; this.anchor.add(catcher);
    this.reticle = new THREE.Mesh(new THREE.RingGeometry(0.06, 0.075, 40).rotateX(-Math.PI / 2), new THREE.MeshBasicMaterial({ color: LIME }));
    const dot = new THREE.Mesh(new THREE.CircleGeometry(0.012, 20).rotateX(-Math.PI / 2), new THREE.MeshBasicMaterial({ color: LIME })); this.reticle.add(dot);
    this.reticle.matrixAutoUpdate = false; this.reticle.visible = false; this.scene.add(this.reticle);
    this.anchor.visible = false; this.anchor.add(this.model); this.model.add(this.hl); this.scene.add(this.anchor);
  }

  static async supported() { try { return !!(navigator.xr && await navigator.xr.isSessionSupported('immersive-ar')); } catch { return false; } }

  async load(path: string) {
    const r = await fetch(`/api/scene3d?path=${encodeURIComponent(path)}`); if (!r.ok) throw new Error('No 3D source for this drawing');
    this.data = await r.json();
    this.model.clear(); this.model.add(this.hl); this.ifcMeshes = [];
    if (this.data!.kind === 'plan') this.buildPlan(this.data as PlanScene); else await this.buildIfc(this.data as IfcScene);
  }

  private buildPlan(s: PlanScene) {
    const [x0, y0, x1, y1] = s.bounds, k = TABLE / Math.max(x1 - x0, y1 - y0);
    this.model.scale.set(k, k * VEX, k); this.model.position.set(-(x0 + x1) / 2 * k, 0, (y0 + y1) / 2 * k);
    const add = (g: THREE.BufferGeometry, m: THREE.Material, y = 0, order = 0) => { const mesh = new THREE.Mesh(g, m); mesh.position.y = y; mesh.castShadow = mesh.receiveShadow = true; mesh.userData.order = order; mesh.visible = false; this.model.add(mesh); return mesh; };
    add(prism([[x0 - .3, y0 - .3], [x1 + .3, y0 - .3], [x1 + .3, y1 + .3], [x0 - .3, y1 + .3]], .06), this.mats.floor, -.06, -1);
    s.rooms.forEach(r => add(prism(r.polygon, .02), this.mats.room, 0, 0));
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    s.walls.forEach(w => add(prism(w.polygon, w.height || 2.7, w.holes || []), this.mats.wall, 0, 1 + Math.hypot(centroid(w.polygon)[0] - cx, centroid(w.polygon)[1] - cy)));
    s.doors.forEach(d => add(prism(d.polygon, .05), this.mats.door, 0, 30));
    s.windows.forEach(w => add(prism(w.polygon, 1.3), this.mats.glass, .9, 30));
  }

  private async buildIfc(s: IfcScene) {
    const gltf = await new GLTFLoader().loadAsync(s.glb);
    const root = gltf.scene; root.rotation.x = -Math.PI / 2; root.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(root), size = box.getSize(new THREE.Vector3()), c = box.getCenter(new THREE.Vector3());
    const k = TABLE / Math.max(size.x, size.z);
    const wrap = new THREE.Group(); wrap.add(root); root.position.set(-c.x, -box.min.y, -c.z);
    this.model.scale.set(k, k * VEX * .7, k); this.model.add(wrap);
    const storey = new Map(s.elements.map(e => [e.guid, e.storey ?? null]));
    root.traverse(o => { const m = o as THREE.Mesh; if (!m.isMesh) return; const name = m.name || m.parent?.name || ''; const cut = name.indexOf('_');
      const cls = name.slice(0, cut); m.material = this.mats.wall; m.castShadow = true; m.visible = false;
      const wb = new THREE.Box3().setFromObject(m); m.userData.order = wb.min.y * 3 + 1; m.userData.space = cls === 'IfcSpace';
      this.ifcMeshes.push({ mesh: m, cls, storey: storey.get(name.slice(cut + 1)) ?? null }); });
  }

  async start(overlay: HTMLElement) {
    const session = await navigator.xr!.requestSession('immersive-ar', { requiredFeatures: ['hit-test'], optionalFeatures: ['dom-overlay', 'local-floor'], domOverlay: { root: overlay } } as XRSessionInit);
    this.session = session; document.body.appendChild(this.renderer.domElement);
    this.renderer.xr.setReferenceSpaceType('local'); await this.renderer.xr.setSession(session);
    this.refSpace = this.renderer.xr.getReferenceSpace();
    const viewer = await session.requestReferenceSpace('viewer');
    this.hitSource = (await session.requestHitTestSource!({ space: viewer })) ?? null;
    session.addEventListener('select', () => { if (!this.placed && this.reticle.visible) this.place(); });
    session.addEventListener('end', () => { this.hitSource?.cancel(); this.hitSource = null; this.session = null; this.placed = false; this.renderer.setAnimationLoop(null); this.renderer.domElement.remove(); this.onEnd?.(); });
    this.renderer.setAnimationLoop((_t, frame) => this.frame(frame));
  }

  end() { void this.session?.end(); }
  replace() { this.placed = false; this.anchor.visible = false; }

  private place() {
    this.anchor.position.setFromMatrixPosition(this.reticle.matrix);
    // Face the building toward the viewer.
    const cam = this.renderer.xr.getCamera(); const p = new THREE.Vector3().setFromMatrixPosition(cam.matrixWorld);
    this.anchor.rotation.set(0, Math.atan2(p.x - this.anchor.position.x, p.z - this.anchor.position.z), 0);
    this.anchor.visible = true; this.placed = true; this.reticle.visible = false;
    this.construct(); this.onPlaced?.();
  }

  /** Floor first, then walls rise from the centre outwards, then openings: the building constructs itself. */
  construct() {
    const now = performance.now(); this.anims = [];
    const parts = this.data?.kind === 'ifc' ? this.ifcMeshes.filter(m => !m.mesh.userData.space).map(m => m.mesh) : this.model.children.filter(c => (c as THREE.Mesh).isMesh) as THREE.Mesh[];
    const orders = parts.map(p => p.userData.order as number), lo = Math.min(...orders), hi = Math.max(...orders);
    parts.forEach(p => { p.visible = false; const d = 2600 * ((p.userData.order - lo) / Math.max(1e-6, hi - lo)); this.anims.push({ obj: p, t0: now + 200 + d, dur: 700, kind: this.data?.kind === 'ifc' ? 'show' : 'grow' }); });
  }

  /** Light up the evidence for an answer, one item at a time. */
  highlight(a: XrAnswer | null) {
    this.hl.clear(); this.anims = this.anims.filter(x => x.kind !== 'pop');
    if (this.data?.kind === 'ifc') {
      const cls = a?.model_fact?.element?.startsWith('Ifc') ? a.model_fact.element : a?.explanation?.match(/Ifc[A-Z][A-Za-z]+/)?.[0] || '';
      const targets = this.ifcMeshes.filter(m => cls && m.cls === cls).sort((p, q) => p.mesh.userData.order - q.mesh.userData.order);
      const tset = new Set(targets.map(t => t.mesh));
      this.ifcMeshes.forEach(m => { m.mesh.material = targets.length ? (tset.has(m.mesh) ? this.mats.pending : this.mats.ghost) : this.mats.wall; m.mesh.visible = !m.mesh.userData.space || tset.has(m.mesh); });
      this.reveal(targets.map(t => () => { t.mesh.material = this.mats.lit; }));
      return;
    }
    const s = this.data as PlanScene | null; if (!s || !a || a.abstained) { this.onCount?.(0, 0); return; }
    const kind = a.scene_kind || ''; let polys: Poly[][] = [];
    if (s.raster && a.evidence?.length) {
      const { m_per_px: m, cx, cy } = s.raster; const to = (x: number, y: number): [number, number] => [(x - cx) * m, -(y - cy) * m];
      polys = a.evidence.map(e => { const [x0, y0, x1, y1] = e.bbox; return [[to(x0, y0), to(x1, y0), to(x1, y1), to(x0, y1)]]; });
    } else {
      let list: { polygon: Poly; name?: string | null }[] = kind === 'doors' ? s.doors : kind === 'windows' ? s.windows : kind === 'fixtures' ? s.fixtures : kind === 'units' ? s.unit_outlines || [] : [];
      if (kind === 'rooms') { const names = (a.scene_room_names || []).map(n => n.toLowerCase()); list = s.rooms.filter(r => r.name && (!names.length || names.some(n => r.name!.toLowerCase().includes(n)))); }
      // CAD draws one door as several parts: merge nearby parts, picking the radius that matches the verified count.
      const expected = typeof a.value === 'number' ? a.value : 0;
      const group = (r: number) => { const out: Poly[][] = []; const cs: [number, number][] = []; for (const it of list) { const c = centroid(it.polygon) as [number, number]; const i = r > 0 ? cs.findIndex(d => Math.hypot(c[0] - d[0], c[1] - d[1]) < r) : -1; if (i >= 0) out[i].push(it.polygon); else { out.push([it.polygon]); cs.push(c); } } return out; };
      polys = group(0);
      if (['doors', 'windows', 'fixtures'].includes(kind) && expected && list.length > expected) { for (let r = .1; r <= 1.5; r += .05) { const g = group(r); if (Math.abs(g.length - expected) < Math.abs(polys.length - expected)) polys = g; if (g.length === expected) break; } }
    }
    const [h, y] = ({ windows: [1.3, .9], doors: [2.1, 0], rooms: [.15, 0], units: [.12, 0] } as Record<string, number[]>)[kind] || [1, 0];
    polys.sort((p, q) => centroid(p[0])[0] - centroid(q[0])[0]);
    this.reveal(polys.map(group => () => { group.forEach(poly => { const m = new THREE.Mesh(prism(poly, h), this.mats.lit); m.position.y = y; m.castShadow = true; this.hl.add(m); this.anims.push({ obj: m, t0: performance.now(), dur: 420, kind: 'pop' }); }); }));
  }

  private reveal(steps: (() => void)[]) {
    this.onCount?.(0, steps.length);
    const step = Math.max(80, Math.min(400, 2200 / Math.max(1, steps.length)));
    steps.forEach((fn, i) => setTimeout(() => { fn(); this.onTick?.(i + 1); this.onCount?.(i + 1, steps.length); if (i === steps.length - 1) this.onDone?.(); }, 500 + i * step));
    if (!steps.length) this.onDone?.();
  }

  private frame(frame?: XRFrame) {
    if (frame && this.hitSource && this.refSpace && !this.placed) {
      const hits = frame.getHitTestResults(this.hitSource);
      if (hits.length) { const pose = hits[0].getPose(this.refSpace); if (pose) { this.reticle.visible = true; this.reticle.matrix.fromArray(pose.transform.matrix); } }
      else this.reticle.visible = false;
    }
    const now = performance.now();
    for (const a of this.anims) {
      const p = (now - a.t0) / a.dur; if (p < 0) continue;
      a.obj.visible = true; const e = ease(p);
      if (a.kind === 'grow') a.obj.scale.y = Math.max(.001, e);
      else if (a.kind === 'pop') a.obj.scale.y = Math.max(.001, ease(p * 1.2));
    }
    this.anims = this.anims.filter(a => now - a.t0 < a.dur + 50);
    this.renderer.render(this.scene, this.camera);
  }
}
