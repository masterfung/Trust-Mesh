"use client";

import { useEffect, useState, useRef, Suspense, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { api, EmergencyAccessResponse, EmergencyCapsule } from "@/lib/api";

// ── Role theming ─────────────────────────────────────────────────────────────

const ROLE_CONFIG: Record<
  string,
  { label: string; emoji: string; headerBg: string; border: string; accent: string; accentBg: string }
> = {
  paramedic: {
    label: "PARAMEDIC / EMT",
    emoji: "🚑",
    headerBg: "bg-red-950",
    border: "border-red-700",
    accent: "text-red-400",
    accentBg: "bg-red-950/50",
  },
  er_nurse: {
    label: "ER NURSE",
    emoji: "🏥",
    headerBg: "bg-blue-950",
    border: "border-blue-700",
    accent: "text-blue-400",
    accentBg: "bg-blue-950/50",
  },
  attending_physician: {
    label: "ATTENDING PHYSICIAN",
    emoji: "👨‍⚕️",
    headerBg: "bg-emerald-950",
    border: "border-emerald-700",
    accent: "text-emerald-400",
    accentBg: "bg-emerald-950/50",
  },
};

// ── Data extraction helpers ───────────────────────────────────────────────────

function extractBloodType(capsules: EmergencyCapsule[]): string | null {
  for (const cap of capsules) {
    const text = cap.title + " " + cap.content;
    const m = text.match(/blood\s*type[:\s]+([ABO]{1,3}[+-])/i);
    if (m) return m[1].toUpperCase();
  }
  return null;
}

function extractDNR(capsules: EmergencyCapsule[]): boolean | null {
  for (const cap of capsules) {
    const text = (cap.title + " " + cap.content).toLowerCase();
    if (/\bdnr\b|do not resuscitate/.test(text)) return true;
  }
  return null;
}

function extractAllergies(capsules: EmergencyCapsule[]): string[] {
  for (const cap of capsules) {
    if (!/allerg/i.test(cap.title + cap.content)) continue;
    const content = cap.content;
    const bulletItems: string[] = [];
    for (const line of content.split("\n")) {
      const m = line.match(/^[-•*]\s*(.+)/);
      if (m) bulletItems.push(m[1].trim());
    }
    if (bulletItems.length > 0) return bulletItems.slice(0, 4);
    // Fallback: comma-separated
    const comma = content.split(",").map((s) => s.trim()).filter(Boolean);
    if (comma.length >= 2) return comma.slice(0, 4);
  }
  return [];
}

function extractContacts(capsules: EmergencyCapsule[]): string[] {
  for (const cap of capsules) {
    if (!/emergency.contact|contact/i.test(cap.title)) continue;
    return cap.content.split("\n").map((l) => l.trim()).filter(Boolean).slice(0, 2);
  }
  return [];
}

// ── Content formatter ─────────────────────────────────────────────────────────

function FormatContent({ content }: { content: string }) {
  // Strip leading category header if it matches the capsule title
  const cleaned = content.replace(/^(?:ALLERGIES|Current medications?|Emergency contacts?)[:\s]*\n*/i, "");
  const lines = cleaned.split("\n");
  const bulletLines = lines.filter((l) => /^[-•*]\s/.test(l.trim()));

  if (bulletLines.length >= 2) {
    return (
      <ul className="space-y-1">
        {bulletLines.map((line, i) => (
          <li key={i} className="flex items-start gap-2 text-sm text-white/80">
            <span className="text-white/40 mt-0.5">•</span>
            <span>{line.replace(/^[-•*]\s/, "").trim()}</span>
          </li>
        ))}
      </ul>
    );
  }
  return <p className="text-sm text-white/80 leading-relaxed whitespace-pre-wrap">{cleaned}</p>;
}

// ── Capsule card ──────────────────────────────────────────────────────────────

const CATEGORY_ICONS: Record<string, string> = {
  health: "❤️",
  medical: "💊",
  medication: "💊",
  allergy: "⚠️",
  emergency: "🚨",
  contact: "📞",
  insurance: "🏦",
  personal: "👤",
};

function CapsuleCard({ capsule }: { capsule: EmergencyCapsule }) {
  const [expanded, setExpanded] = useState(false);
  const preview = capsule.content.slice(0, 240);
  const isLong = capsule.content.length > 240;
  const icon = CATEGORY_ICONS[capsule.category?.toLowerCase() ?? ""] ?? "📋";

  return (
    <div className="bg-white/5 border border-white/10 rounded-xl p-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-base">{icon}</span>
          <h3 className="font-semibold text-white text-sm">{capsule.title}</h3>
        </div>
        {capsule.category && (
          <span className="text-[10px] px-2 py-0.5 bg-white/10 text-white/50 rounded-full shrink-0">
            {capsule.category}
          </span>
        )}
      </div>
      <div>
        {expanded ? (
          <FormatContent content={capsule.content} />
        ) : (
          <FormatContent content={preview + (isLong ? "…" : "")} />
        )}
      </div>
      {isLong && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-xs text-white/40 hover:text-white/70 transition-colors"
        >
          {expanded ? "Show less" : "Show more →"}
        </button>
      )}
    </div>
  );
}

// ── Alert Family panel ────────────────────────────────────────────────────────

function AlertFamilyPanel({
  token,
  patient,
  podUrl,
  role,
}: {
  token: string;
  patient: string;
  podUrl: string | undefined;
  role: string;
}) {
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState<{ notified: number; members: string[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isListening, setIsListening] = useState(false);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recognitionRef = useRef<any>(null);

  const cfg = ROLE_CONFIG[role] ?? ROLE_CONFIG["paramedic"];

  const startListening = useCallback(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const win = window as any;
    const SR = win.SpeechRecognition ?? win.webkitSpeechRecognition;
    if (!SR) return;
    const recognition = new SR();
    recognition.lang = "en-US";
    recognition.continuous = false;
    recognition.interimResults = false;
    recognitionRef.current = recognition;
    const priorText = message.trimEnd();
    const prefix = priorText ? priorText + " " : "";
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    recognition.onresult = (e: any) => {
      const transcript = Array.from(e.results as SpeechRecognitionResultList)
        .filter((r) => r.isFinal)
        .map((r) => r[0].transcript)
        .join(" ");
      setMessage(prefix + transcript);
    };
    recognition.onend = () => setIsListening(false);
    recognition.onerror = () => setIsListening(false);
    recognition.start();
    setIsListening(true);
  }, [message]);

  const stopListening = useCallback(() => {
    recognitionRef.current?.stop();
    setIsListening(false);
  }, []);

  const sendAlert = async () => {
    if (!message.trim()) return;
    setSending(true);
    setError(null);
    try {
      const result = await api.sendEmergencyAlert(token, patient, message.trim(), podUrl);
      setSent(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to send");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className={`border ${cfg.border} rounded-xl overflow-hidden`}>
      <button
        onClick={() => setOpen(!open)}
        className={`w-full flex items-center justify-between px-4 py-3 ${cfg.accentBg} hover:brightness-110 transition-all`}
      >
        <div className="flex items-center gap-2">
          <span className="text-lg">📢</span>
          <span className={`font-semibold text-sm ${cfg.accent}`}>Send Update to Family</span>
        </div>
        <svg
          width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
          className={`text-white/40 transition-transform ${open ? "rotate-180" : ""}`}
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {open && (
        <div className="px-4 py-4 bg-white/3 space-y-3">
          {sent ? (
            <div className="flex items-start gap-3 p-3 bg-green-950/40 border border-green-700/40 rounded-lg">
              <span className="text-green-400 text-lg mt-0.5">✓</span>
              <div>
                <p className="text-green-400 text-sm font-medium">
                  Sent to {sent.notified} family member{sent.notified !== 1 ? "s" : ""}
                </p>
                {sent.members.length > 0 && (
                  <p className="text-white/50 text-xs mt-0.5">{sent.members.join(", ")}</p>
                )}
              </div>
            </div>
          ) : (
            <>
              <p className="text-xs text-white/50">
                Your message will be delivered as a notification to the patient&apos;s family network.
              </p>
              <div className="relative">
                <textarea
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  placeholder="e.g. Patient stable after car accident, en route to Riverside General…"
                  maxLength={500}
                  rows={3}
                  className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2.5 text-sm text-white placeholder-white/30 resize-none focus:outline-none focus:border-white/25"
                />
                <span className="absolute bottom-2 right-3 text-[10px] text-white/30">
                  {message.length}/500
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={isListening ? stopListening : startListening}
                  className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-all ${
                    isListening
                      ? "bg-red-500/20 text-red-400 animate-pulse"
                      : "bg-white/10 text-white/60 hover:text-white hover:bg-white/15"
                  }`}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
                    <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
                    <line x1="12" y1="19" x2="12" y2="23"/>
                    <line x1="8" y1="23" x2="16" y2="23"/>
                  </svg>
                  {isListening ? "Stop" : "🎤 Dictate"}
                </button>
                <button
                  onClick={sendAlert}
                  disabled={!message.trim() || sending}
                  className={`flex-1 sm:flex-none sm:ml-auto flex items-center justify-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold transition-all disabled:opacity-40 disabled:cursor-not-allowed ${cfg.accentBg} ${cfg.accent} border ${cfg.border} hover:brightness-125`}
                >
                  {sending ? (
                    <svg className="animate-spin w-3 h-3" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                    </svg>
                  ) : (
                    <>Send Update →</>
                  )}
                </button>
              </div>
              {error && <p className="text-xs text-red-400">{error}</p>}
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main scan view ────────────────────────────────────────────────────────────

function ScanView() {
  const searchParams = useSearchParams();
  const token = searchParams.get("t") ?? "";
  const patient = searchParams.get("p") ?? "";
  const podUrl = searchParams.get("pod") ?? undefined;

  const [data, setData] = useState<EmergencyAccessResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(0);

  // Live clock for countdown
  useEffect(() => {
    const tInit = setTimeout(() => setNow(Date.now()), 0);
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => {
      clearTimeout(tInit);
      clearInterval(t);
    };
  }, []);

  useEffect(() => {
    if (!token || !patient) {
      const t = setTimeout(() => {
        setError("Missing token or patient parameter in QR URL.");
        setLoading(false);
      }, 0);
      return () => clearTimeout(t);
    }
    api
      .getEmergencyQrData(token, patient, podUrl)
      .then((d) => {
        setData(d);
        setLoading(false);
      })
      .catch((e) => {
        const msg = e instanceof Error ? e.message : String(e);
        if (msg.toLowerCase().includes("expired")) {
          setError("QR code has expired. Ask the patient to refresh their Emergency ID.");
        } else if (msg.toLowerCase().includes("revoked")) {
          setError("This token has been revoked.");
        } else if (msg.toLowerCase().includes("signature")) {
          setError("Token signature is invalid. The QR code may be corrupted.");
        } else {
          setError(msg);
        }
        setLoading(false);
      });
  }, [token, patient, podUrl]);

  if (loading) {
    return (
      <div className="min-h-screen bg-[#050510] flex items-center justify-center">
        <div className="text-center space-y-4">
          <div className="w-14 h-14 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto" />
          <p className="text-white/60 text-sm">Verifying emergency token…</p>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="min-h-screen bg-[#050510] flex items-center justify-center p-4">
        <div className="max-w-md w-full text-center space-y-4">
          <div className="w-16 h-16 rounded-full bg-red-950 border-2 border-red-700 flex items-center justify-center mx-auto">
            <span className="text-2xl">⚠️</span>
          </div>
          <h2 className="text-xl font-bold text-red-400">Access Denied</h2>
          <p className="text-white/60 text-sm">{error ?? "Unknown error"}</p>
          <p className="text-white/40 text-xs">
            Contact the patient or their emergency contact for assistance.
          </p>
        </div>
      </div>
    );
  }

  const role = data.role;
  const cfg = ROLE_CONFIG[role] ?? ROLE_CONFIG["paramedic"];
  const expiresAt = new Date(data.expires_at);
  const msLeft = expiresAt.getTime() - now;
  const expired = msLeft <= 0;
  const TOKEN_DURATION_SECS = 1800; // 30 min
  const progressPct = expired ? 0 : Math.min(100, (msLeft / (TOKEN_DURATION_SECS * 1000)) * 100);
  const progressColor = msLeft < 120_000 ? "bg-red-500" : msLeft < 300_000 ? "bg-amber-500" : "bg-green-500";
  const secsLeft = Math.ceil(msLeft / 1000);

  const expiryLabel = expiresAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  // Extract critical facts
  const bloodType = extractBloodType(data.capsules);
  const hasDNR = extractDNR(data.capsules);
  const allergies = extractAllergies(data.capsules);
  const contacts = extractContacts(data.capsules);
  const totalCapsules = data.total_capsules ?? data.capsule_count;
  const hasFamily = !!data.family_notified;

  return (
    <div className="min-h-screen bg-[#050510] text-white relative">
      {/* Expiry overlay */}
      {expired && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
          <div className="text-center p-8 max-w-sm">
            <div className="text-5xl mb-4">⏰</div>
            <h2 className="text-2xl font-bold text-amber-400 mb-2">Token Expired</h2>
            <p className="text-white/60 text-sm mb-4">
              This QR code has expired. Contact the patient to refresh their Emergency ID.
            </p>
            <p className="text-white/30 text-xs">
              Data loaded before expiry is shown below for reference.
            </p>
          </div>
        </div>
      )}

      {/* Role header */}
      <div className={`${cfg.headerBg} border-b-2 ${cfg.border} px-4 py-4`}>
        <div className="max-w-2xl mx-auto">
          <div className="flex items-start justify-between gap-3 min-w-0">
            <div className="min-w-0">
              <p className={`text-[10px] font-bold tracking-widest ${cfg.accent} uppercase`}>
                Emergency Access
              </p>
              <h1 className="text-lg sm:text-xl font-bold text-white mt-0.5 truncate">
                {cfg.emoji} {cfg.label}
              </h1>
            </div>
            <div className="text-right shrink-0">
              <p className="text-white/50 text-xs">Patient</p>
              <p className="font-semibold text-white text-sm">{data.patient_name}</p>
              <p className={`text-xs mt-0.5 ${expired ? "text-red-400" : msLeft < 120_000 ? "text-amber-400" : "text-white/50"}`}>
                {expired ? "Expired" : `Valid until ${expiryLabel}`}
              </p>
            </div>
          </div>

          {/* Countdown progress bar */}
          <div className="mt-3 h-1 bg-white/10 rounded-full overflow-hidden">
            <div
              className={`h-full ${progressColor} transition-all duration-1000`}
              style={{ width: `${progressPct}%` }}
            />
          </div>
          {!expired && secsLeft < 120 && (
            <p className="text-xs text-red-400 mt-1 text-right animate-pulse">
              {secsLeft}s remaining
            </p>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="max-w-2xl mx-auto px-4 py-5 space-y-5">

        {/* Critical facts panel */}
        <div className={`${cfg.accentBg} border ${cfg.border} rounded-xl p-4 space-y-3`}>
          <p className={`text-[10px] font-bold tracking-widest ${cfg.accent} uppercase`}>
            Critical Information
          </p>

          {/* Blood type + DNR row */}
          <div className="flex flex-wrap items-center gap-2">
            {bloodType ? (
              <div className="flex items-center gap-1.5 px-3 py-1.5 bg-red-500/20 border border-red-500/40 rounded-lg">
                <span className="text-base">🩸</span>
                <span className="font-bold text-red-300 text-sm">{bloodType}</span>
              </div>
            ) : (
              <div className="flex items-center gap-1.5 px-3 py-1.5 bg-white/5 border border-white/10 rounded-lg">
                <span className="text-base">🩸</span>
                <span className="text-white/40 text-xs">Blood type not on file</span>
              </div>
            )}

            {hasDNR === true ? (
              <div className="flex items-center gap-1.5 px-3 py-1.5 bg-red-600/25 border border-red-500/50 rounded-lg">
                <span className="text-base">⛔</span>
                <span className="font-bold text-red-300 text-sm">DNR on file — Do Not Resuscitate</span>
              </div>
            ) : (
              <div className="flex items-center gap-1.5 px-3 py-1.5 bg-green-950/40 border border-green-700/30 rounded-lg">
                <span className="text-green-400 text-sm">✓</span>
                <span className="text-green-300 text-xs">No DNR (Resuscitate)</span>
              </div>
            )}
          </div>

          {/* Allergies */}
          {allergies.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              <span className="text-white/50 text-xs self-center">Allergies:</span>
              {allergies.map((a, i) => (
                <span key={i} className="px-2 py-0.5 bg-amber-500/15 border border-amber-500/30 text-amber-300 text-xs rounded-full">
                  ⚠️ {a}
                </span>
              ))}
            </div>
          )}

          {/* Emergency contacts */}
          {contacts.length > 0 && (
            <div className="space-y-1">
              <p className="text-white/50 text-xs">Emergency contacts:</p>
              {contacts.map((c, i) => {
                const phone = c.match(/[\d\s\-().+]{7,}/)?.[0]?.trim();
                return (
                  <div key={i} className="text-sm text-white/80">
                    {phone ? (
                      <a href={`tel:${phone.replace(/\s/g, "")}`} className="text-blue-300 underline">
                        {c}
                      </a>
                    ) : c}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Access + scope banner */}
        <div className="flex items-center gap-3 p-3 bg-green-950/40 border border-green-700/40 rounded-lg">
          <span className="text-green-400 text-lg">✓</span>
          <div className="flex-1">
            <p className="text-green-400 text-sm font-medium">Access verified</p>
            <p className="text-white/50 text-xs">
              Viewing {data.capsule_count} of {totalCapsules} records
              {role === "paramedic"
                ? " — limited to emergency essentials"
                : role === "er_nurse"
                  ? " — clinical emergency access"
                  : " — full clinical access"}
              {" · "}Audit logged
            </p>
          </div>
          {hasFamily && (
            <span className="shrink-0 text-[10px] text-white/40 bg-white/5 px-2 py-1 rounded">
              Family notified
            </span>
          )}
        </div>

        {/* Capsule cards */}
        {data.capsules.length === 0 ? (
          <div className="text-center py-10 text-white/40">
            <p>No accessible records found for this role.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {data.capsules.map((cap) => (
              <CapsuleCard key={cap.id} capsule={cap} />
            ))}
          </div>
        )}

        {/* FHIR bundle link */}
        <div className="border-t border-white/10 pt-3">
          <a
            href={`/emergency/${data.audit_id}/fhir`}
            className="flex items-center justify-center gap-2 py-2.5 px-4 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-sm text-white/60 hover:text-white transition-colors"
          >
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14 2 14 8 20 8"/>
            </svg>
            View Full FHIR Bundle →
          </a>
        </div>

        {/* Alert family panel */}
        {hasFamily && (
          <AlertFamilyPanel
            token={token}
            patient={patient}
            podUrl={podUrl}
            role={role}
          />
        )}

        {/* Footer */}
        <p className="text-center text-white/25 text-xs pb-4">
          Audit ID: <span className="font-mono">{data.audit_id}</span>
        </p>
      </div>
    </div>
  );
}

// Wrap in Suspense for useSearchParams
export default function EmergencyScanPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-[#050510] flex items-center justify-center">
          <div className="w-10 h-10 border-2 border-white border-t-transparent rounded-full animate-spin" />
        </div>
      }
    >
      <ScanView />
    </Suspense>
  );
}
