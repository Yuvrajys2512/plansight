import { useEffect, useRef, useState } from 'react';
import { useConversation } from '@elevenlabs/react';

type Ans = { value?: unknown; unit?: string | null; evidence?: unknown[]; method?: string; cost_usd?: number; naive_cost_usd?: number; abstained?: boolean; reason?: string; explanation?: string } | null;
type Props = { ask: (q: string) => Promise<Ans>; openDrawing: (query: string) => string; flyTo: (room: string) => string; context: string };
type Line = { who: 'you' | 'ai'; text: string; id: number };

/** "Talk to the drawing": ElevenLabs voice agent whose tools drive the same /api/ask pipeline and evidence replay. */
export default function Voice({ ask, openDrawing, flyTo, context }: Props) {
  const [open, setOpen] = useState(false);
  const [lines, setLines] = useState<Line[]>([]);
  const [tool, setTool] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const orb = useRef<HTMLDivElement>(null);
  const seq = useRef(0);
  const askRef = useRef(ask); askRef.current = ask;
  const openRef = useRef(openDrawing); openRef.current = openDrawing;
  const flyRef = useRef(flyTo); flyRef.current = flyTo;

  const conv = useConversation({
    clientTools: {
      ask_plansight: async ({ question }: { question?: string }) => {
        setTool(`asking: ${question}`);
        const a = await askRef.current(String(question || ''));
        setTool(null);
        if (!a) return JSON.stringify({ abstained: true, reason: 'PlanSight was busy, ask again.' });
        return JSON.stringify({ value: a.value, unit: a.unit, evidence_count: a.evidence?.length ?? 0, method: a.method, cost_usd: a.cost_usd, frontier_cost_usd: a.naive_cost_usd, abstained: !!a.abstained, reason: a.reason, explanation: a.explanation });
      },
      open_drawing: ({ query }: { query?: string }) => openRef.current(String(query || '')),
      fly_to: ({ room }: { room?: string }) => { setTool(`flying to ${room}`); setTimeout(() => setTool(null), 2500); return flyRef.current(String(room || '')); },
    },
    onMessage: (m: { message?: string; source?: string; role?: string }) => {
      const who = (m.role || m.source) === 'user' ? 'you' : 'ai';
      if (!m.message) return;
      setLines(v => [...v.slice(-3), { who, text: m.message!, id: ++seq.current }]);
    },
    onError: (e: unknown) => setErr(typeof e === 'string' ? e : 'Voice connection error'),
  });
  const live = conv.status === 'connected';

  // Keep the agent aware of which drawing is on screen.
  useEffect(() => { if (live) conv.sendContextualUpdate(`The engineer now has this drawing open: ${context}`); }, [context, live]); // eslint-disable-line react-hooks/exhaustive-deps

  // Orb reacts to whoever is talking.
  useEffect(() => {
    if (!live) return; let raf = 0;
    const tick = () => { const v = Math.max(conv.getOutputVolume(), conv.getInputVolume() * 0.8); orb.current?.style.setProperty('--v', String(Math.min(1, v * 2.2))); raf = requestAnimationFrame(tick); };
    raf = requestAnimationFrame(tick); return () => cancelAnimationFrame(raf);
  }, [live]); // eslint-disable-line react-hooks/exhaustive-deps

  const start = async () => {
    setErr(null); setOpen(true); setLines([]);
    try {
      await navigator.mediaDevices.getUserMedia({ audio: true });
      const r = await fetch('/api/voice/token'); if (!r.ok) throw new Error('Voice mode is not configured on this server.');
      const { token } = await r.json();
      conv.startSession({ conversationToken: token, connectionType: 'webrtc', dynamicVariables: {} });
    } catch (e) { setErr(e instanceof Error ? e.message : 'Microphone permission is needed.'); }
  };
  const stop = () => { conv.endSession(); };

  if (!open) return <button className="voice-fab" onClick={() => void start()}><span className="fab-orb" />Ask by voice</button>;
  return <div className={`voice-panel ${live ? 'live' : ''} ${conv.isSpeaking ? 'speaking' : ''}`}>
    <div className="voice-top"><span className="kicker">Voice mode · ElevenLabs</span><button className="x" onClick={() => { stop(); setOpen(false); }}>✕</button></div>
    <div className="orb-wrap"><div className="orb" ref={orb}><i /><i /><i /></div></div>
    <div className="voice-state">{err ? <span className="warn">{err}</span> : conv.status === 'connecting' ? 'Connecting…' : live ? (tool ? <span className="tool">◌ {tool}</span> : conv.isSpeaking ? 'PlanSight is speaking' : 'Listening… ask in any language') : 'Disconnected'}</div>
    <div className="voice-lines">{lines.map(l => <p key={l.id} className={l.who}><b>{l.who === 'you' ? 'You' : 'PlanSight'}</b>{l.text}</p>)}</div>
    <div className="voice-actions">{live ? <button className="btn-ghost sm" onClick={stop}>End conversation</button> : <button className="btn-primary" onClick={() => void start()}>Start talking</button>}</div>
  </div>;
}
