import { useEffect, useRef, useState } from 'react';
import QRCode from 'qrcode';

export type SnapInfo = { path: string; width: number; height: number; warped: boolean; t: number };

/** Downscale on the device (phones shoot 12+ MP) and send as JPEG. */
export async function uploadImage(file: Blob, session: string | null): Promise<SnapInfo> {
  const bmp = await createImageBitmap(file);
  const s = Math.min(1, 2600 / Math.max(bmp.width, bmp.height));
  const c = document.createElement('canvas'); c.width = Math.round(bmp.width * s); c.height = Math.round(bmp.height * s);
  c.getContext('2d')!.drawImage(bmp, 0, 0, c.width, c.height);
  const r = await fetch('/api/upload', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ image: c.toDataURL('image/jpeg', 0.9), session }) });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'Upload failed');
  return r.json();
}

const newSession = () => Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);

/** Desktop: QR code for the phone + drag-and-drop. Polls for the phone's photo. */
export function SnapModal({ onClose, onImage }: { onClose: () => void; onImage: (s: SnapInfo) => void }) {
  const [session] = useState(newSession);
  const [qr, setQr] = useState('');
  const [state, setState] = useState<'idle' | 'uploading' | 'error'>('idle');
  const [err, setErr] = useState('');
  const [drag, setDrag] = useState(false);
  const opened = useRef(Date.now() / 1000);
  const url = `${location.origin}/?snap=${session}`;
  useEffect(() => { QRCode.toDataURL(url, { margin: 1, width: 360, color: { dark: '#05080d', light: '#ffffff' } }).then(setQr).catch(() => {}); }, [url]);
  useEffect(() => {
    const t = setInterval(() => { fetch(`/api/snap/${session}`).then(r => r.json()).then((s: SnapInfo) => { if (s?.path && s.t > opened.current) { clearInterval(t); onImage(s); } }).catch(() => {}); }, 1300);
    return () => clearInterval(t);
  }, [session]); // eslint-disable-line react-hooks/exhaustive-deps
  const send = async (f?: File | null) => {
    if (!f) return; setState('uploading');
    try { onImage(await uploadImage(f, null)); } catch (e) { setState('error'); setErr(e instanceof Error ? e.message : 'Upload failed'); }
  };
  return <div className="snap-backdrop" onClick={onClose}>
    <div className="snap-modal" onClick={e => e.stopPropagation()}>
      <button className="x" onClick={onClose}>✕</button>
      <span className="kicker">Bring your own drawing</span>
      <h2>Snap any floor plan.<br />Watch it rise.</h2>
      <div className="snap-cols">
        <div className="qr">{qr ? <img src={qr} alt="QR code to open the phone camera page" /> : <div className="qr-ph" />}<p><b>Scan with your phone</b> and photograph a printed plan. It appears here in seconds.</p><div className="waiting"><i className="pulse" /> waiting for your photo…</div></div>
        <label className={`drop ${drag ? 'over' : ''}`} onDragOver={e => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={e => { e.preventDefault(); setDrag(false); void send(e.dataTransfer.files[0]); }}>
          <input type="file" accept="image/*" onChange={e => void send(e.target.files?.[0])} hidden />
          <span className="drop-icon">⬆</span><b>{state === 'uploading' ? 'Straightening & reading…' : 'Drop a plan image'}</b><small>{state === 'error' ? err : 'or click to choose · PNG / JPG · photos are de-skewed automatically'}</small>
        </label>
      </div>
      <p className="snap-foot">PlanSight finds the sheet, undoes the perspective, flattens the lighting, counts the doors with the fine-tuned detector, then lifts the walls into 3D. Works best on residential plans like the CubiCasa ones.</p>
    </div>
  </div>;
}

/** Phone page opened from the QR code. */
export function PhoneSnap({ session }: { session: string }) {
  const [state, setState] = useState<'ready' | 'preview' | 'sending' | 'sent' | 'error'>('ready');
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState('');
  const [err, setErr] = useState('');
  const pick = (f?: File | null) => { if (!f) return; setFile(f); setPreview(URL.createObjectURL(f)); setState('preview'); };
  const send = async () => { if (!file) return; setState('sending'); try { await uploadImage(file, session); setState('sent'); } catch (e) { setErr(e instanceof Error ? e.message : 'Upload failed'); setState('error'); } };
  return <main className="phone">
    <div className="phone-brand"><span className="brandmark">◎</span><b>PlanSight</b></div>
    {state === 'sent' ? <div className="phone-done"><div className="big-check">✓</div><h1>Sent!</h1><p>Look at the big screen 👀<br />Your plan is being read and lifted into 3D.</p><button className="btn-ghost" onClick={() => { setState('ready'); setFile(null); setPreview(''); }}>Snap another</button></div> : <>
      <h1>Photograph a floor plan</h1>
      <p>Hold the phone flat above the sheet. Edges of the paper visible is perfect: we straighten it automatically.</p>
      {preview && <img className="phone-preview" src={preview} alt="Your photo" />}
      {state === 'preview' || state === 'sending' ? <div className="phone-actions"><button className="btn-primary big" disabled={state === 'sending'} onClick={() => void send()}>{state === 'sending' ? 'Sending…' : 'Send to PlanSight →'}</button><label className="btn-ghost">Retake<input type="file" accept="image/*" capture="environment" hidden onChange={e => pick(e.target.files?.[0])} /></label></div>
        : <div className="phone-actions"><label className="btn-primary big">📷 Take photo<input type="file" accept="image/*" capture="environment" hidden onChange={e => pick(e.target.files?.[0])} /></label><label className="btn-ghost">Choose from gallery<input type="file" accept="image/*" hidden onChange={e => pick(e.target.files?.[0])} /></label></div>}
      {state === 'error' && <p className="phone-err">{err}</p>}
    </>}
  </main>;
}
