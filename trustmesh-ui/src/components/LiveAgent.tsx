"use client";
import QRCode from "react-qr-code";

/**
 * LiveAgent — real-time bidirectional voice interface powered by Gemini Live.
 *
 * Connects to /api/live/stream (server-proxied WebSocket).
 * Server handles Gemini Live session + TrustMesh tool execution with full DB access.
 *
 * Audio pipeline:
 *   Mic → AudioContext(16kHz) → AudioWorklet → Int16 PCM → base64 → WS → Server → Gemini
 *   Gemini → Server → WS → base64 → Int16 PCM → Float32 → AudioContext(24kHz) → Speaker
 */

import { useState, useRef, useEffect, useCallback } from "react";
import { getPodUrl } from "@/lib/api";

// ── AudioWorklet source (inlined as a Blob to avoid needing a public/ file) ──
const WORKLET_SOURCE = `
class PcmProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0]?.[0];
    if (ch && ch.length > 0) {
      // Convert Float32 → Int16
      const i16 = new Int16Array(ch.length);
      for (let i = 0; i < ch.length; i++) {
        const s = Math.max(-1, Math.min(1, ch[i]));
        i16[i] = s < 0 ? s * 32768 : s * 32767;
      }
      this.port.postMessage(i16.buffer, [i16.buffer]);
    }
    return true;
  }
}
registerProcessor("pcm-processor", PcmProcessor);
`;

type LiveStatus = "idle" | "connecting" | "active" | "error";

interface ToolActivity {
  name: string;
  status: "calling" | "done";
  preview?: string;
}

interface Props {
  userId: string;
  onClose: () => void;
}

// ── Tool icon + label mapping ─────────────────────────────────────────────
const TOOL_META: Record<string, { icon: string; label: string }> = {
  search_vault: { icon: "🔍", label: "Searching vault" },
  save_capsule: { icon: "💾", label: "Saving to vault" },
  query_peer: { icon: "🤝", label: "Querying peer" },
  check_calendar: { icon: "📅", label: "Checking calendar" },
  discover_agents: { icon: "🌐", label: "Discovering agents" },
  list_connections: { icon: "👥", label: "Listing connections" },
  web_search: { icon: "🌍", label: "Searching web" },
  create_timeline_entry: { icon: "⏰", label: "Creating reminder" },
  list_timeline_entries: { icon: "📋", label: "Checking reminders" },
  trigger_emergency: { icon: "🚨", label: "Emergency escalation" },
};

function toolLabel(name: string): string {
  return TOOL_META[name]?.label ?? name;
}
function toolIcon(name: string): string {
  return TOOL_META[name]?.icon ?? "🔧";
}

// ── Waveform: 5 animated bars ─────────────────────────────────────────────
function Waveform({ active }: { active: boolean }) {
  const bars = [0.4, 0.8, 1.0, 0.7, 0.5]; // relative heights
  return (
    <div className="flex items-end gap-0.5 h-5">
      {bars.map((h, i) => (
        <div
          key={i}
          className="w-1 rounded-full bg-blue-400"
          style={{
            height: active ? `${h * 100}%` : "20%",
            transition: "height 0.1s ease",
            animation: active ? `waveBar${i} 0.8s ease-in-out infinite alternate` : "none",
            animationDelay: `${i * 0.12}s`,
            opacity: active ? 1 : 0.3,
          }}
        />
      ))}
      <style>{`
        @keyframes waveBar0 { from { height: 20% } to { height: 40% } }
        @keyframes waveBar1 { from { height: 35% } to { height: 80% } }
        @keyframes waveBar2 { from { height: 50% } to { height: 100% } }
        @keyframes waveBar3 { from { height: 30% } to { height: 70% } }
        @keyframes waveBar4 { from { height: 20% } to { height: 50% } }
      `}</style>
    </div>
  );
}

export function LiveAgent({ userId, onClose }: Props) {
  const [status, setStatus] = useState<LiveStatus>("idle");
  const [transcript, setTranscript] = useState<{ role: "user" | "agent"; text: string }[]>([]);
  const [tools, setTools] = useState<ToolActivity[]>([]);
  const [agentSpeaking, setAgentSpeaking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [podUrl, setPodUrl] = useState<string>("");

  const wsRef = useRef<WebSocket | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const playbackCtxRef = useRef<AudioContext | null>(null);
  const playQueueRef = useRef<AudioBuffer[]>([]);
  const playingRef = useRef(false);
  const transcriptEndRef = useRef<HTMLDivElement>(null);

  // Capture pod URL on mount
  useEffect(() => {
    setPodUrl(getPodUrl());
  }, []);

  // Scroll to bottom of transcript on updates
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [transcript]);

  // ── PCM Playback ─────────────────────────────────────────────────────────

  const playNextChunk = useCallback(() => {
    if (playQueueRef.current.length === 0) {
      playingRef.current = false;
      setAgentSpeaking(false);
      return;
    }
    const ctx = playbackCtxRef.current;
    if (!ctx) return;

    setAgentSpeaking(true);
    const buf = playQueueRef.current.shift()!;
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(ctx.destination);
    src.onended = playNextChunk;
    src.start();
    playingRef.current = true;
  }, []);

  const enqueueAudio = useCallback(
    (base64: string) => {
      const ctx = playbackCtxRef.current;
      if (!ctx) return;

      const raw = atob(base64);
      const i16 = new Int16Array(raw.length / 2);
      for (let i = 0; i < i16.length; i++) {
        i16[i] = raw.charCodeAt(i * 2) | (raw.charCodeAt(i * 2 + 1) << 8);
      }
      const f32 = new Float32Array(i16.length);
      for (let i = 0; i < i16.length; i++) f32[i] = i16[i] / 32768;

      const buf = ctx.createBuffer(1, f32.length, 24000);
      buf.copyToChannel(f32, 0);
      playQueueRef.current.push(buf);

      if (!playingRef.current) playNextChunk();
    },
    [playNextChunk]
  );

  // ── Session lifecycle ─────────────────────────────────────────────────────

  const startSession = useCallback(async () => {
    setStatus("connecting");
    setError(null);
    setTranscript([]);
    setTools([]);

    try {
      // 1. Playback AudioContext (24kHz output from Gemini)
      playbackCtxRef.current = new AudioContext({ sampleRate: 24000 });

      // 2. Capture AudioContext + AudioWorklet (16kHz PCM → server)
      const captureCtx = new AudioContext({ sampleRate: 16000 });
      audioCtxRef.current = captureCtx;

      const workletBlob = new Blob([WORKLET_SOURCE], { type: "application/javascript" });
      const workletUrl = URL.createObjectURL(workletBlob);
      await captureCtx.audioWorklet.addModule(workletUrl);
      URL.revokeObjectURL(workletUrl);

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        video: false,
      });
      streamRef.current = stream;

      const source = captureCtx.createMediaStreamSource(stream);
      const worklet = new AudioWorkletNode(captureCtx, "pcm-processor");
      workletNodeRef.current = worklet;
      source.connect(worklet);

      // 3. WebSocket to server proxy
      const currentPodUrl = getPodUrl();
      setPodUrl(currentPodUrl);
      const wsUrl = currentPodUrl.replace(/^http/, "ws");
      const tz = encodeURIComponent(Intl.DateTimeFormat().resolvedOptions().timeZone);
      const ws = new WebSocket(`${wsUrl}/api/live/stream?tz=${tz}`);
      wsRef.current = ws;

      ws.onopen = () => {
        setStatus("active");
        // Wire AudioWorklet → WebSocket
        worklet.port.onmessage = (e: MessageEvent) => {
          if (ws.readyState !== WebSocket.OPEN) return;
          const i16 = new Int16Array(e.data as ArrayBuffer);
          // Build base64 from raw bytes (little-endian Int16)
          const bytes = new Uint8Array(i16.buffer);
          let binary = "";
          for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
          ws.send(JSON.stringify({ type: "audio", data: btoa(binary) }));
        };
      };

      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data as string);
          if (msg.type === "audio") {
            enqueueAudio(msg.data);
          } else if (msg.type === "text") {
            setTranscript((prev) => {
              // Append to last agent turn or start a new one
              const last = prev[prev.length - 1];
              if (last?.role === "agent") {
                return [...prev.slice(0, -1), { role: "agent", text: last.text + msg.text }];
              }
              return [...prev, { role: "agent", text: msg.text }];
            });
          } else if (msg.type === "transcript") {
            setTranscript((prev) => {
              const last = prev[prev.length - 1];
              if (last?.role === "user") {
                return [...prev.slice(0, -1), { role: "user", text: last.text + msg.text }];
              }
              return [...prev, { role: "user", text: msg.text }];
            });
          } else if (msg.type === "tool_call") {
            setTools((prev) => [
              { name: msg.name, status: "calling" },
              ...prev.slice(0, 4),
            ]);
          } else if (msg.type === "tool_result") {
            setTools((prev) =>
              prev.map((t) =>
                t.name === msg.name && t.status === "calling"
                  ? { ...t, status: "done", preview: msg.result }
                  : t
              )
            );
          } else if (msg.type === "error") {
            setError(msg.message);
            setStatus("error");
          }
        } catch {
          // non-JSON frame, ignore
        }
      };

      ws.onerror = () => {
        setError("WebSocket connection failed. Is the server running?");
        setStatus("error");
      };

      ws.onclose = (ev) => {
        if (status === "active" || status === "connecting") {
          if (ev.code === 4001) {
            setError("Authentication required — please log in first.");
          }
          setStatus("idle");
        }
      };
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start live session");
      setStatus("error");
      cleanup();
    }
  }, [enqueueAudio, status]);

  const cleanup = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;

    workletNodeRef.current?.disconnect();
    workletNodeRef.current = null;

    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;

    audioCtxRef.current?.close();
    audioCtxRef.current = null;

    playbackCtxRef.current?.close();
    playbackCtxRef.current = null;

    playQueueRef.current = [];
    playingRef.current = false;
    setAgentSpeaking(false);
  }, []);

  const stopSession = useCallback(() => {
    cleanup();
    setStatus("idle");
  }, [cleanup]);

  // Cleanup on unmount
  useEffect(() => () => cleanup(), [cleanup]);

  // ── Helpers ───────────────────────────────────────────────────────────────

  // Format pod URL for display: strip http(s):// + trailing slash
  const podDisplayUrl = podUrl
    .replace(/^https?:\/\//, "")
    .replace(/\/$/, "")
    || "localhost:9000";

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center p-4 bg-black/60 backdrop-blur-sm">
      <div className="bg-gray-900 border border-gray-700 rounded-2xl w-full max-w-lg shadow-2xl flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800">
          <div className="flex items-center gap-3">
            {/* Waveform when agent is speaking, dot otherwise */}
            {status === "active" && agentSpeaking ? (
              <Waveform active={true} />
            ) : (
              <div
                className={`w-3 h-3 rounded-full ${
                  status === "active"
                    ? "bg-green-400"
                    : status === "connecting"
                    ? "bg-yellow-400 animate-pulse"
                    : status === "error"
                    ? "bg-red-400"
                    : "bg-gray-600"
                }`}
              />
            )}
            <div>
              <span className="font-semibold text-white text-sm">
                {status === "idle" && "Live Agent"}
                {status === "connecting" && "Connecting…"}
                {status === "active" && (agentSpeaking ? "Agent speaking…" : "Listening…")}
                {status === "error" && "Connection error"}
              </span>
              {/* Pod URL — shown when active */}
              {status === "active" && (
                <div className="text-xs text-gray-500 font-mono mt-0.5">
                  {podDisplayUrl}
                </div>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white transition-colors text-lg leading-none"
          >
            ✕
          </button>
        </div>

        {/* Transcript */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-2 min-h-[220px] max-h-[340px]">
          {transcript.length === 0 && status !== "active" && (
            <div className="text-center text-gray-500 text-sm mt-8">
              <p className="text-2xl mb-2">🎙️</p>
              <p>Press <strong>Start</strong> to begin a live voice conversation</p>
              <p className="text-xs mt-1 text-gray-600">Your agent has full access to your vault and trust network</p>
            </div>
          )}
          {transcript.length === 0 && status === "active" && (
            <div className="text-center text-gray-500 text-sm mt-8">
              <p className="text-2xl mb-2 animate-pulse">👂</p>
              <p>Speak now — I&apos;m listening</p>
            </div>
          )}
          {transcript.map((t, i) => {
            const scanUrls = t.role === "agent"
              ? (t.text.match(/https?:\/\/\S+\/emergency\/scan\?\S+/g) ?? [])
              : [];
            return (
              <div key={i} className={`flex flex-col ${t.role === "user" ? "items-end" : "items-start"}`}>
                <div
                  className={`max-w-[85%] rounded-2xl px-4 py-2 text-sm leading-relaxed ${
                    t.role === "user"
                      ? "bg-blue-600 text-white rounded-br-sm"
                      : "bg-gray-800 text-gray-100 rounded-bl-sm"
                  }`}
                >
                  {t.text}
                </div>
                {scanUrls.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-3 max-w-[85%]">
                    {[...new Set(scanUrls)].map((url, j) => {
                      let parsed: URL | null = null;
                      try { parsed = new URL(url); } catch { return null; }
                      const patient = parsed.searchParams.get("p") ?? "patient";
                      const roleHint = url.includes("paramedic") ? "Paramedic"
                        : url.includes("attending") ? "Physician"
                        : url.includes("er_nurse") ? "ER Nurse" : "Emergency";
                      return (
                        <div key={j} className="flex flex-col items-center gap-2 p-3 bg-red-950/40 border border-red-700/40 rounded-xl">
                          <span className="text-red-400 text-xs font-semibold">🚑 {roleHint} — {patient}</span>
                          <div className="bg-white p-2 rounded-lg"><QRCode value={url} size={130} /></div>
                          <a href={url} target="_blank" rel="noopener noreferrer" className="text-xs text-red-300 underline">Open scan →</a>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
          <div ref={transcriptEndRef} />
        </div>

        {/* Tool activity strip — inline chips */}
        {tools.length > 0 && (
          <div className="px-5 pb-3 flex flex-wrap gap-1.5">
            {tools.slice(0, 5).map((t, i) => (
              <div
                key={i}
                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${
                  t.status === "calling"
                    ? "bg-yellow-900/60 text-yellow-300 border border-yellow-700/50"
                    : "bg-gray-800 text-gray-400 border border-gray-700/50"
                }`}
              >
                <span>{toolIcon(t.name)}</span>
                <span className={t.status === "calling" ? "animate-pulse" : ""}>
                  {toolLabel(t.name)}
                </span>
                {t.status === "done" && (
                  <span className="text-green-500">✓</span>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="mx-5 mb-3 p-3 bg-red-900/40 border border-red-700 rounded-lg text-red-300 text-sm">
            {error}
          </div>
        )}

        {/* Controls */}
        <div className="px-5 py-4 border-t border-gray-800 flex gap-3">
          {status === "idle" || status === "error" ? (
            <button
              onClick={startSession}
              className="flex-1 bg-blue-600 hover:bg-blue-500 text-white font-medium py-2.5 rounded-xl transition-colors flex items-center justify-center gap-2"
            >
              <span>🎙️</span> Start Live Session
            </button>
          ) : (
            <button
              onClick={stopSession}
              className="flex-1 bg-red-600 hover:bg-red-500 text-white font-medium py-2.5 rounded-xl transition-colors flex items-center justify-center gap-2"
            >
              <span>⏹</span> End Session
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
