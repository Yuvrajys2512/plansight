// Tiny synthesized sound effects (WebAudio, no files). Muted state persists per viewer.
let ctx: AudioContext | null = null;
let muted = (() => { try { return localStorage.getItem('ps-muted') === '1'; } catch { return false; } })();
const listeners = new Set<(m: boolean) => void>();

function ac() {
  if (muted) return null;
  try { ctx = ctx || new AudioContext(); if (ctx.state === 'suspended') void ctx.resume(); return ctx; } catch { return null; }
}
function tone(freq: number, dur: number, type: OscillatorType, gain: number, endFreq?: number, delay = 0) {
  const a = ac(); if (!a) return;
  const t = a.currentTime + delay, o = a.createOscillator(), g = a.createGain();
  o.type = type; o.frequency.setValueAtTime(freq, t); if (endFreq) o.frequency.exponentialRampToValueAtTime(endFreq, t + dur);
  g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(gain, t + 0.008); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  o.connect(g).connect(a.destination); o.start(t); o.stop(t + dur + 0.02);
}
function noise(dur: number, from: number, to: number, gain: number) {
  const a = ac(); if (!a) return;
  const t = a.currentTime, buf = a.createBuffer(1, Math.floor(a.sampleRate * dur), a.sampleRate), d = buf.getChannelData(0);
  for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
  const src = a.createBufferSource(), f = a.createBiquadFilter(), g = a.createGain();
  src.buffer = buf; f.type = 'bandpass'; f.Q.value = 1.2; f.frequency.setValueAtTime(from, t); f.frequency.exponentialRampToValueAtTime(to, t + dur);
  g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(gain, t + dur * 0.4); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  src.connect(f).connect(g).connect(a.destination); src.start(t); src.stop(t + dur);
}

export const sfx = {
  /** Count tick; pitch climbs with the count so a long count "rises". */
  tick(i: number) { tone(520 * Math.pow(2, Math.min(i, 36) / 24), 0.07, 'triangle', 0.09); },
  /** Final answer stamp. */
  stamp() { tone(140, 0.25, 'sine', 0.35, 60); tone(1320, 0.12, 'triangle', 0.06, undefined, 0.02); tone(1760, 0.18, 'triangle', 0.05, undefined, 0.09); },
  /** Scan / thinking start. */
  scan() { noise(0.9, 400, 2400, 0.05); },
  /** Walls rising into 3D. */
  whoosh() { noise(1.6, 180, 1400, 0.12); tone(80, 1.4, 'sine', 0.12, 160); },
  /** Floors separating. */
  split() { tone(220, 0.5, 'sine', 0.1, 330); tone(330, 0.5, 'sine', 0.06, 495, 0.08); },
  /** Rejecting a box. */
  reject() { tone(300, 0.14, 'square', 0.04, 150); },
  isMuted: () => muted,
  setMuted(m: boolean) { muted = m; try { localStorage.setItem('ps-muted', m ? '1' : '0'); } catch { /* storage unavailable */ } listeners.forEach(l => l(m)); },
  subscribe(l: (m: boolean) => void) { listeners.add(l); return () => { listeners.delete(l); }; },
};
