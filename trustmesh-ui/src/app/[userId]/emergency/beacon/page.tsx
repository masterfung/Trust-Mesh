"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import QRCode from "react-qr-code";
import { api, EmergencyBeaconResponse } from "@/lib/api";

type RoleKey = "paramedic" | "er_nurse" | "attending_physician";

const ROLES: { key: RoleKey; label: string; emoji: string; color: string; bgColor: string; sees: string[] }[] = [
  {
    key: "paramedic",
    label: "EMT / Paramedic",
    emoji: "🚑",
    color: "text-red-400",
    bgColor: "border-red-700 bg-red-950/60",
    sees: ["Blood type", "Allergies", "DNR status", "Emergency contact"],
  },
  {
    key: "er_nurse",
    label: "ER Nurse",
    emoji: "🏥",
    color: "text-blue-400",
    bgColor: "border-blue-700 bg-blue-950/60",
    sees: ["Blood type", "Weight / Height", "Allergies", "Emergency contact", "DNR status"],
  },
  {
    key: "attending_physician",
    label: "Attending Physician",
    emoji: "👨‍⚕️",
    color: "text-emerald-400",
    bgColor: "border-emerald-700 bg-emerald-950/60",
    sees: ["Full medication list", "Conditions & diagnoses", "Allergies", "Surgery history", "Insurance", "DNR status"],
  },
];

function CountdownTimer({ expiresIn, onExpired }: { expiresIn: number; onExpired: () => void }) {
  const [remaining, setRemaining] = useState(expiresIn);

  useEffect(() => {
    const interval = setInterval(() => {
      setRemaining((r) => {
        if (r <= 1) {
          clearInterval(interval);
          onExpired();
          return 0;
        }
        return r - 1;
      });
    }, 1000);
    return () => clearInterval(interval);
  }, [onExpired]);

  const mins = Math.floor(remaining / 60);
  const secs = remaining % 60;
  const isLow = remaining < 60;

  return (
    <span className={isLow ? "text-red-400 font-bold animate-pulse" : "text-yellow-400 font-mono"}>
      {String(mins).padStart(2, "0")}:{String(secs).padStart(2, "0")}
    </span>
  );
}

export default function EmergencyBeaconPage() {
  const params = useParams();
  const userId = params.userId as string;

  const [activeRole, setActiveRole] = useState<RoleKey>("paramedic");
  const [beacon, setBeacon] = useState<EmergencyBeaconResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expired, setExpired] = useState(false);
  const [skipEmptyCheck, setSkipEmptyCheck] = useState(false);

  const fetchBeacon = useCallback(async () => {
    setLoading(true);
    setError(null);
    setExpired(false);
    try {
      const data = await api.generateEmergencyBeacon(userId);
      setBeacon(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to generate beacon");
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    fetchBeacon();
  }, [fetchBeacon]);

  const activeRoleConfig = ROLES.find((r) => r.key === activeRole)!;
  const qrUrl = beacon?.qr_urls?.[activeRole] ?? "";

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0a0a0f] flex items-center justify-center">
        <div className="text-center space-y-4">
          <div className="w-12 h-12 border-2 border-red-500 border-t-transparent rounded-full animate-spin mx-auto" />
          <p className="text-muted-foreground">Generating emergency tokens…</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-[#0a0a0f] flex items-center justify-center p-4">
        <div className="max-w-md w-full bg-red-950/40 border border-red-700 rounded-xl p-6 text-center space-y-4">
          <p className="text-2xl">⚠️</p>
          <p className="text-red-400 font-medium">{error}</p>
          <button
            onClick={fetchBeacon}
            className="px-4 py-2 bg-red-700 hover:bg-red-600 text-white rounded-lg text-sm transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  // No medical data — show setup prompt instead of empty QR codes
  if (beacon && beacon.capsule_count === 0 && !skipEmptyCheck) {
    return (
      <div className="min-h-screen bg-[#0a0a0f] flex items-center justify-center p-4">
        <div className="max-w-md w-full space-y-6 text-center">
          <div className="text-6xl">🏥</div>
          <div className="space-y-2">
            <h1 className="text-2xl font-bold text-white">No Medical Data Found</h1>
            <p className="text-muted-foreground text-sm leading-relaxed">
              Your Emergency Medical ID QR codes are ready, but you haven&apos;t added any health
              information to your vault yet. First responders who scan your code won&apos;t see anything useful.
            </p>
          </div>
          <div className="bg-yellow-950/40 border border-yellow-700/60 rounded-xl p-4 text-left space-y-2">
            <p className="text-yellow-400 text-sm font-medium">Recommended health data to add:</p>
            <ul className="text-yellow-300/80 text-sm space-y-1">
              <li>• Blood type &amp; allergies</li>
              <li>• Current medications</li>
              <li>• Emergency contacts</li>
              <li>• Medical conditions or DNR status</li>
            </ul>
          </div>
          <div className="flex flex-col gap-3">
            <a
              href={`/${userId}/vault`}
              className="block w-full py-3 bg-accent hover:bg-accent-hover text-accent-fg font-semibold rounded-xl text-sm transition-colors"
            >
              Add Health Data to Vault
            </a>
            <button
              onClick={() => setSkipEmptyCheck(true)}
              className="w-full py-2.5 bg-white/5 hover:bg-white/10 text-muted-foreground hover:text-white rounded-xl text-sm border border-white/10 transition-colors"
            >
              Show QR Codes Anyway
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white p-4 md:p-8">
      <div className="max-w-lg mx-auto space-y-6">
        {/* Header */}
        <div className="text-center space-y-1">
          <h1 className="text-2xl font-bold text-red-400">🚨 Emergency Medical ID</h1>
          <p className="text-muted-foreground text-sm">
            {beacon?.patient_name ?? "Patient"}
          </p>
          <div className="flex items-center justify-center gap-2 text-sm">
            <span className="text-muted-foreground">Expires in</span>
            {beacon && !expired ? (
              <CountdownTimer expiresIn={beacon.expires_in} onExpired={() => setExpired(true)} />
            ) : (
              <span className="text-red-400 font-bold">EXPIRED</span>
            )}
          </div>
          {beacon && (
            <p className="text-xs text-muted-foreground">
              Audit: <span className="font-mono">{beacon.audit_id.slice(0, 8)}…</span>
            </p>
          )}
        </div>

        {/* Role tabs */}
        <div className="flex rounded-lg overflow-hidden border border-white/10">
          {ROLES.map((r) => (
            <button
              key={r.key}
              onClick={() => setActiveRole(r.key)}
              className={`flex-1 py-2 px-1 text-xs font-medium transition-colors ${
                activeRole === r.key
                  ? `${r.color} bg-white/10`
                  : "text-muted-foreground hover:text-white hover:bg-white/5"
              }`}
            >
              {r.emoji} {r.label.split(" ")[0]}
            </button>
          ))}
        </div>

        {/* QR Code card */}
        <div className={`rounded-xl border-2 p-6 space-y-5 ${activeRoleConfig.bgColor}`}>
          <div className="text-center">
            <span className={`text-lg font-bold ${activeRoleConfig.color}`}>
              {activeRoleConfig.emoji} {activeRoleConfig.label}
            </span>
          </div>

          {expired ? (
            <div className="flex flex-col items-center gap-3 py-8">
              <p className="text-red-400 font-medium">QR codes have expired</p>
              <button
                onClick={fetchBeacon}
                className="px-4 py-2 bg-red-700 hover:bg-red-600 text-white rounded-lg text-sm transition-colors"
              >
                ⟳ Generate New Codes
              </button>
            </div>
          ) : qrUrl ? (
            <div className="flex flex-col items-center gap-4">
              <div className="bg-white p-4 rounded-xl shadow-lg">
                <QRCode value={qrUrl} size={180} />
              </div>
              <p className="text-xs text-muted-foreground text-center break-all px-2">
                {qrUrl.slice(0, 80)}…
              </p>
            </div>
          ) : (
            <div className="flex justify-center py-8">
              <div className="w-8 h-8 border-2 border-white border-t-transparent rounded-full animate-spin" />
            </div>
          )}

          {/* Scope summary */}
          <div className="space-y-2">
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              This role sees:
            </p>
            <ul className="space-y-1">
              {activeRoleConfig.sees.map((item) => (
                <li key={item} className="flex items-center gap-2 text-sm">
                  <span className="text-green-400">✓</span>
                  <span className="text-white/80">{item}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* Refresh button */}
        <div className="text-center">
          <button
            onClick={fetchBeacon}
            className="px-5 py-2 bg-white/10 hover:bg-white/20 text-white rounded-lg text-sm border border-white/20 transition-colors"
          >
            ⟳ Refresh All Codes
          </button>
        </div>

        {/* Security note */}
        <p className="text-xs text-muted-foreground text-center">
          Tokens are cryptographically signed with your ed25519 key.
          Access is logged to your audit trail and family members are notified.
        </p>
      </div>
    </div>
  );
}
