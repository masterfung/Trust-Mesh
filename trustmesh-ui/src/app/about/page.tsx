"use client";

import Link from "next/link";
import { cn } from "@/lib/utils";
import { useState, useRef } from "react";

/* ═══════════════ TOOLTIP ═══════════════ */

function Tip({ label, desc }: { label: string; desc: string }) {
  const [show, setShow] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  const [pos, setPos] = useState({ top: 0, left: 0 });

  const handleEnter = () => {
    if (ref.current) {
      const rect = ref.current.getBoundingClientRect();
      setPos({
        top: rect.top - 8,
        left: Math.max(8, Math.min(rect.left + rect.width / 2, window.innerWidth - 152)),
      });
    }
    setShow(true);
  };

  return (
    <span
      ref={ref}
      className="relative inline-block cursor-help"
      onMouseEnter={handleEnter}
      onMouseLeave={() => setShow(false)}
      onFocus={handleEnter}
      onBlur={() => setShow(false)}
      tabIndex={0}
    >
      <span className="border-b border-dashed border-current/40">{label}</span>
      {show && (
        <span
          className="fixed z-[9999] w-72 px-3.5 py-3 rounded-xl bg-[#1a1a2e] border border-card-border shadow-2xl text-left pointer-events-none"
          style={{ top: pos.top, left: pos.left, transform: "translate(-50%, -100%)" }}
        >
          <span className="block text-xs font-semibold text-foreground mb-1">{label}</span>
          <span className="block text-[11px] text-foreground/70 leading-relaxed">{desc}</span>
        </span>
      )}
    </span>
  );
}

/* ═══════════════ ACRONYM DESCRIPTIONS ═══════════════ */

const ACRONYMS: Record<string, string> = {
  "A2A": "Agent-to-Agent — Google's open protocol that lets AI agents discover each other and exchange messages across different platforms.",
  "OpenCLAAS": "Open Capability Ledger as a Service — a community-driven registry where agents publish their capabilities so others can find and connect with them.",
  "MCP": "Model Context Protocol — Anthropic's standard for connecting AI models to external tools, databases, and data sources.",
  "UCP": "Unified Context Protocol — Google's protocol for sharing context and tools between AI systems, similar to MCP.",
  "x402": "HTTP 402 Payment Protocol — Coinbase's standard for AI agent micropayments, enabling agents to pay each other for services.",
  "DID": "Decentralized Identifiers — W3C standard for self-sovereign digital identity that works without a central authority.",
  "UCAN": "User Controlled Authorization Networks — Fission's token format for delegatable, offline-verifiable authorization between agents.",
};

/* ═══════════════ DATA ═══════════════ */

type Framework = {
  name: string;
  by: string;
  color: string;
  textColor: string;
};

type LayerDef = {
  name: string;
  color: string;
  borderColor: string;
  bgColor: string;
  frameworks: Framework[];
  gap: string;
};

const LAYERS: LayerDef[] = [
  {
    name: "Discovery",
    color: "text-rose-400",
    borderColor: "border-rose-500/30",
    bgColor: "bg-rose-500/5",
    frameworks: [
      { name: "A2A", by: "Google", color: "bg-blue-500/20", textColor: "text-blue-400" },
      { name: "OpenCLAAS", by: "Community", color: "bg-rose-500/20", textColor: "text-rose-400" },
    ],
    gap: "No trust verification between discovered agents",
  },
  {
    name: "Communication",
    color: "text-blue-400",
    borderColor: "border-blue-500/30",
    bgColor: "bg-blue-500/5",
    frameworks: [
      { name: "A2A", by: "Google", color: "bg-blue-500/20", textColor: "text-blue-400" },
      { name: "MCP", by: "Anthropic", color: "bg-orange-500/20", textColor: "text-orange-400" },
    ],
    gap: "Messages sent in plaintext — no encryption",
  },
  {
    name: "Context",
    color: "text-green-400",
    borderColor: "border-green-500/30",
    bgColor: "bg-green-500/5",
    frameworks: [
      { name: "MCP", by: "Anthropic", color: "bg-orange-500/20", textColor: "text-orange-400" },
      { name: "UCP", by: "Google", color: "bg-green-500/20", textColor: "text-green-400" },
    ],
    gap: "User has no control over data access policies",
  },
  {
    name: "Payment",
    color: "text-indigo-400",
    borderColor: "border-indigo-500/30",
    bgColor: "bg-indigo-500/5",
    frameworks: [
      { name: "x402", by: "Coinbase", color: "bg-indigo-500/20", textColor: "text-indigo-400" },
    ],
    gap: "Payment without trust — can't verify agent identity",
  },
  {
    name: "Identity",
    color: "text-purple-400",
    borderColor: "border-purple-500/30",
    bgColor: "bg-purple-500/5",
    frameworks: [
      { name: "DID", by: "W3C", color: "bg-purple-500/20", textColor: "text-purple-400" },
    ],
    gap: "Identity without authorization or agent integration",
  },
  {
    name: "Authorization",
    color: "text-amber-400",
    borderColor: "border-amber-500/30",
    bgColor: "bg-amber-500/5",
    frameworks: [
      { name: "UCAN", by: "Fission", color: "bg-amber-500/20", textColor: "text-amber-400" },
    ],
    gap: "Auth tokens without data layer or agent orchestration",
  },
  {
    name: "Security",
    color: "text-red-400",
    borderColor: "border-red-500/30",
    bgColor: "bg-red-500/5",
    frameworks: [],
    gap: "No framework scans for prompt injection or multimodal attacks",
  },
];

const MISSING_LAYERS = [
  { name: "Encrypted Vault", desc: "User-owned encrypted data storage" },
  { name: "Trust Scoring", desc: "Multi-hop trust from connections + networks" },
  { name: "Scoped Access", desc: "Role-based, time-bounded data sharing" },
  { name: "Security Scanning", desc: "Text + multimodal prompt injection & data exfiltration detection" },
  { name: "Audit Trail", desc: "Immutable log of every access decision" },
];

const capabilities = [
  "Agent Discovery", "Agent Communication", "Tool Integration",
  "Identity (DID)", "Authorization", "Encryption",
  "Trust Scoring", "Data Sovereignty", "Audit Trail", "Scoped Access",
  "Security Scanning",
];
const coverage: Record<string, Set<string>> = {
  "A2A":       new Set(["Agent Discovery", "Agent Communication"]),
  "MCP":       new Set(["Tool Integration", "Agent Communication"]),
  "UCP":       new Set(["Tool Integration"]),
  "x402":      new Set([]),
  "DID":       new Set(["Identity (DID)"]),
  "UCAN":      new Set(["Authorization", "Scoped Access"]),
  "OpenCLAAS": new Set(["Agent Discovery"]),
  "TrustMesh": new Set(capabilities),
};
const fwNames = ["TrustMesh", "A2A", "MCP", "UCP", "x402", "DID", "UCAN", "OpenCLAAS"];

/* ═══════════════ SVG DIAGRAMS ═══════════════ */

function GapDiagram() {
  return (
    <div className="relative w-full overflow-hidden rounded-2xl border border-card-border bg-card p-6 md:p-8">
      {/* Title */}
      <div className="mb-6">
        <h3 className="text-lg font-semibold mb-1">Today&apos;s Agent Ecosystem</h3>
        <p className="text-sm text-foreground/60">Each framework solves one piece — but critical layers are missing entirely.</p>
      </div>

      {/* Visual: Agents with gap between them */}
      <div className="flex flex-col gap-0">
        {/* The two agents */}
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-2.5 bg-blue-500/10 border border-blue-500/20 rounded-xl px-4 py-3">
            <div className="w-8 h-8 rounded-full bg-blue-500/20 flex items-center justify-center">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-blue-400"><circle cx="12" cy="8" r="4"/><path d="M20 21a8 8 0 0 0-16 0"/></svg>
            </div>
            <div>
              <div className="text-sm font-semibold text-blue-400">Alice&apos;s Agent</div>
              <div className="text-xs text-foreground/50">Asks a question</div>
            </div>
          </div>

          {/* Arrow */}
          <div className="flex-1 flex items-center px-3">
            <div className="flex-1 border-t-2 border-dashed border-foreground/20" />
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-foreground/30 shrink-0"><path d="M5 12h14m-4-4 4 4-4 4"/></svg>
          </div>

          <div className="flex items-center gap-2.5 bg-green-500/10 border border-green-500/20 rounded-xl px-4 py-3">
            <div className="w-8 h-8 rounded-full bg-green-500/20 flex items-center justify-center">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-green-400"><circle cx="12" cy="8" r="4"/><path d="M20 21a8 8 0 0 0-16 0"/></svg>
            </div>
            <div>
              <div className="text-sm font-semibold text-green-400">Bob&apos;s Agent</div>
              <div className="text-xs text-foreground/50">Has the data</div>
            </div>
          </div>
        </div>

        {/* The pipeline with gaps */}
        <div className="grid grid-cols-6 gap-2 text-center">
          {[
            { label: "Discover", status: "partial", note: "A2A" },
            { label: "Authenticate", status: "missing", note: "No trust" },
            { label: "Encrypt", status: "missing", note: "Plaintext" },
            { label: "Scope access", status: "missing", note: "All or nothing" },
            { label: "Respond", status: "partial", note: "MCP/UCP" },
            { label: "Audit", status: "missing", note: "No trail" },
          ].map((step) => (
            <div key={step.label} className="flex flex-col items-center gap-1.5">
              <div className={cn(
                "w-full py-2.5 rounded-lg text-xs font-semibold border",
                step.status === "partial"
                  ? "bg-amber-500/10 border-amber-500/30 text-amber-400"
                  : "bg-red-500/10 border-red-500/30 text-red-400"
              )}>
                {step.status === "missing" ? (
                  <svg className="inline w-3.5 h-3.5 mr-0.5 -mt-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                ) : (
                  <svg className="inline w-3.5 h-3.5 mr-0.5 -mt-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M12 9v2m0 4h.01"/><circle cx="12" cy="12" r="10"/></svg>
                )}
                {step.label}
              </div>
              <span className="text-[11px] text-foreground/50">{step.note}</span>
            </div>
          ))}
        </div>

        {/* Legend */}
        <div className="flex items-center gap-5 mt-5 text-xs text-foreground/50">
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-sm bg-red-500/40" />
            <span>Missing — no framework covers this</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-sm bg-amber-500/40" />
            <span>Partial — exists but incomplete</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function ProtocolFlowDiagram() {
  const steps = [
    { num: "1", label: "Trust\nResolve", icon: "trust", color: "text-green-400", bg: "bg-green-500/10", border: "border-green-500/30", desc: "Connection + network trust analysis" },
    { num: "2", label: "Citadel\nInput Scan", icon: "shield", color: "text-red-400", bg: "bg-red-500/10", border: "border-red-500/30", desc: "Text + multimodal injection detection" },
    { num: "3", label: "Semantic\nRetrieval", icon: "search", color: "text-blue-400", bg: "bg-blue-500/10", border: "border-blue-500/30", desc: "Vector search over encrypted capsules" },
    { num: "4", label: "Opus 4.6\nReasoning", icon: "brain", color: "text-purple-400", bg: "bg-purple-500/10", border: "border-purple-500/30", desc: "Trust-aware response generation" },
    { num: "5", label: "Citadel\nOutput Scan", icon: "shield", color: "text-red-400", bg: "bg-red-500/10", border: "border-red-500/30", desc: "Data exfiltration + leak detection" },
    { num: "6", label: "Audit &\nRespond", icon: "log", color: "text-amber-400", bg: "bg-amber-500/10", border: "border-amber-500/30", desc: "Log decision + return response" },
  ];

  const icons: Record<string, React.ReactNode> = {
    trust: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg>,
    shield: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>,
    search: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>,
    brain: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="12" cy="12" r="3"/><path d="M12 1v2m0 18v2M4.22 4.22l1.42 1.42m12.72 12.72l1.42 1.42M1 12h2m18 0h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>,
    log: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>,
  };

  return (
    <div className="rounded-2xl border border-card-border bg-card p-6 md:p-8">
      <h3 className="text-lg font-semibold mb-1">The TrustMesh Query Protocol</h3>
      <p className="text-sm text-foreground/60 mb-6">Every cross-agent query passes through this 6-step pipeline. No shortcuts.</p>

      {/* Flow diagram */}
      <div className="flex flex-col gap-0">
        {/* Source agent */}
        <div className="flex items-center gap-2.5 mb-4 ml-2">
          <div className="w-6 h-6 rounded-full bg-blue-500/30 flex items-center justify-center">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="text-blue-400"><circle cx="12" cy="8" r="4"/><path d="M20 21a8 8 0 0 0-16 0"/></svg>
          </div>
          <span className="text-sm text-foreground/60">Incoming query from another agent</span>
        </div>

        {/* Steps */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2.5">
          {steps.map((step, i) => (
            <div key={i} className="relative">
              <div className={cn("rounded-xl border p-4 h-full flex flex-col items-center text-center gap-2 transition-all hover:scale-[1.02]", step.bg, step.border)}>
                <div className="flex items-center gap-2">
                  <span className={cn("text-xl font-bold opacity-50", step.color)}>{step.num}</span>
                  <div className={step.color}>{icons[step.icon]}</div>
                </div>
                <div className={cn("text-sm font-semibold leading-tight whitespace-pre-line", step.color)}>
                  {step.label}
                </div>
                <div className="text-xs text-foreground/50 leading-snug mt-auto">
                  {step.desc}
                </div>
              </div>
              {/* Arrow between steps */}
              {i < steps.length - 1 && (
                <div className="hidden lg:block absolute -right-3 top-1/2 -translate-y-1/2 z-10 text-foreground/30">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"><path d="M5 12h14m-4-4 4 4-4 4"/></svg>
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Response */}
        <div className="flex items-center gap-2.5 mt-4 ml-2">
          <div className="w-6 h-6 rounded-full bg-green-500/30 flex items-center justify-center">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="text-green-400"><polyline points="20 6 9 17 4 12"/></svg>
          </div>
          <span className="text-sm text-foreground/60">Trust-verified, audited response returned</span>
        </div>
      </div>
    </div>
  );
}

function CitadelCallout() {
  return (
    <div className="rounded-2xl border border-red-500/20 bg-gradient-to-br from-red-500/5 to-transparent p-6 md:p-8">
      <div className="flex items-start gap-4">
        <div className="w-12 h-12 rounded-xl bg-red-500/10 border border-red-500/20 flex items-center justify-center shrink-0">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-red-400"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
        </div>
        <div className="flex-1">
          <h3 className="text-lg font-semibold mb-1">
            Powered by <a href="https://trymighty.ai" target="_blank" rel="noopener noreferrer" className="text-red-400 hover:text-red-300 transition-colors">Mighty&apos;s Citadel</a>
          </h3>
          <p className="text-sm text-foreground/70 mb-4">
            Every query and response passes through Citadel&apos;s security scanner — guarding against prompt injection, data exfiltration, and adversarial attacks.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <a href="https://github.com/TryMightyAI/citadel" target="_blank" rel="noopener noreferrer" className="rounded-xl border border-card-border bg-card p-4 block hover:border-green-500/40 transition-colors">
              <div className="flex items-center gap-2 mb-2">
                <div className="px-2 py-0.5 rounded-md bg-green-500/10 border border-green-500/20 text-green-400 text-[11px] font-bold">OSS</div>
                <span className="text-sm font-semibold">Citadel Open Source</span>
              </div>
              <p className="text-sm text-foreground/60">Text-based input/output scanning. Detects prompt injection and data exfiltration in text payloads. Free and open source.</p>
            </a>
            <a href="https://trymighty.ai" target="_blank" rel="noopener noreferrer" className="rounded-xl border border-red-500/20 bg-red-500/5 p-4 block hover:border-red-500/40 transition-colors">
              <div className="flex items-center gap-2 mb-2">
                <div className="px-2 py-0.5 rounded-md bg-red-500/10 border border-red-500/20 text-red-400 text-[11px] font-bold">PRO</div>
                <span className="text-sm font-semibold">Citadel Pro</span>
              </div>
              <p className="text-sm text-foreground/60">Full multimodal protection — scans images, audio, documents, and video for adversarial attacks, steganography, and hidden instructions.</p>
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}

function EmergencyFlowDiagram() {
  const steps = [
    { actor: "Hospital", action: "Issues UCAN token", detail: "Scoped to attending_physician, 2hr expiry, ed25519 signed", color: "text-amber-400", bg: "bg-amber-500/10", icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2z"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/></svg> },
    { actor: "Bob's Agent", action: "Validates token", detail: "Checks signature, expiry, audience DID, and issuer registry", color: "text-blue-400", bg: "bg-blue-500/10", icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg> },
    { actor: "Scope Filter", action: "Role-based filtering", detail: "Doctor: meds, allergies, conditions. Nurse: blood type, vitals only", color: "text-green-400", bg: "bg-green-500/10", icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg> },
    { actor: "Audit System", action: "Logs everything", detail: "Actor, role, capsules accessed, decision reasoning, timestamp", color: "text-purple-400", bg: "bg-purple-500/10", icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg> },
    { actor: "Bob", action: "Gets notified", detail: "\"Riverside Hospital accessed your medical data at 2:34 AM\"", color: "text-cyan-400", bg: "bg-cyan-500/10", icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg> },
  ];

  return (
    <div className="rounded-2xl border border-card-border bg-card p-6 md:p-8">
      <div className="flex items-start justify-between mb-6">
        <div>
          <h3 className="text-lg font-semibold mb-1">Emergency Access Protocol</h3>
          <p className="text-sm text-foreground/60">Bob collapses at the hospital. His doctor needs his medical data — now.</p>
        </div>
        <div className="shrink-0 px-3 py-1.5 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-xs font-semibold">
          <Tip label="UCAN" desc={ACRONYMS["UCAN"]} />
        </div>
      </div>

      <div className="flex flex-col">
        {steps.map((step, i) => (
          <div key={i} className="flex gap-3.5 relative">
            {/* Connector line */}
            {i < steps.length - 1 && (
              <div className="absolute left-[17px] top-[38px] bottom-0 w-px bg-card-border" />
            )}
            {/* Icon circle */}
            <div className={cn("w-[35px] h-[35px] rounded-full shrink-0 flex items-center justify-center border relative z-10", step.bg, `border-${step.color.replace('text-', '')}/30`)}>
              <span className={step.color}>{step.icon}</span>
            </div>
            {/* Content */}
            <div className="pb-5 flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className={cn("text-sm font-bold", step.color)}>{step.actor}</span>
                <span className="text-sm text-foreground">{step.action}</span>
              </div>
              <p className="text-sm text-foreground/50 mt-0.5">{step.detail}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Role scope table */}
      <div className="mt-5 pt-5 border-t border-card-border">
        <p className="text-xs font-semibold text-foreground/60 mb-3 uppercase tracking-wider">Role-Based Scoping</p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5">
          {[
            { role: "Doctor", scope: "Medications, allergies, conditions, history", color: "border-green-500/30 bg-green-500/5" },
            { role: "ER Nurse", scope: "Blood type, weight, height, allergies", color: "border-blue-500/30 bg-blue-500/5" },
            { role: "Paramedic", scope: "Blood type, allergies, DNR status", color: "border-amber-500/30 bg-amber-500/5" },
            { role: "Admin", scope: "Insurance, emergency contacts, next of kin", color: "border-purple-500/30 bg-purple-500/5" },
          ].map((r) => (
            <div key={r.role} className={cn("rounded-lg border p-3", r.color)}>
              <div className="text-xs font-bold text-foreground">{r.role}</div>
              <div className="text-xs text-foreground/50 mt-1 leading-relaxed">{r.scope}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ═══════════════ TAB COMPONENTS ═══════════════ */

function EnvironmentTab() {
  return (
    <div className="space-y-8">
      {/* Layer map */}
      <div>
        <h2 className="text-xl font-bold mb-1">The Agent Framework Landscape</h2>
        <p className="text-sm text-foreground/60 mb-5">Seven frameworks across seven layers. Each solves one piece — none solves the whole puzzle.</p>

        <div className="rounded-2xl border border-card-border bg-card">
          {/* Layer rows */}
          {LAYERS.map((layer, i) => (
            <div key={layer.name} className={cn("flex items-center gap-4 px-5 py-3.5 border-b border-card-border/50 last:border-b-0 hover:bg-card-hover/30 transition-colors", i % 2 === 0 ? "bg-transparent" : "bg-card-hover/10")}>
              {/* Layer label */}
              <div className="w-28 shrink-0">
                <span className={cn("text-sm font-bold", layer.color)}>{layer.name}</span>
              </div>
              {/* Framework chips */}
              <div className="flex items-center gap-2 flex-1">
                {layer.frameworks.length > 0 ? layer.frameworks.map((fw) => (
                  <div key={`${layer.name}-${fw.name}`} className={cn("px-3 py-1.5 rounded-lg text-xs font-semibold border", fw.color, fw.textColor, `border-${fw.textColor.replace('text-', '')}/20`)}>
                    <Tip label={fw.name} desc={ACRONYMS[fw.name] || fw.name} />
                    <span className="text-[10px] font-normal text-foreground/40 ml-1.5">{fw.by}</span>
                  </div>
                )) : (
                  <span className="text-xs text-foreground/30 italic">No framework exists</span>
                )}
              </div>
              {/* Gap indicator */}
              <div className="text-xs text-red-400 flex items-center gap-1.5 shrink-0 max-w-[240px]">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="shrink-0"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                <span className="hidden md:inline text-foreground/50">{layer.gap}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Missing layers callout */}
      <div className="rounded-2xl border border-red-500/20 bg-red-500/5 p-5">
        <div className="flex items-center gap-2 mb-3">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-red-400"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
          <span className="text-sm font-semibold text-red-400">No framework provides these</span>
        </div>
        <div className="flex flex-wrap gap-2">
          {MISSING_LAYERS.map((m) => (
            <div key={m.name} className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-background/50 border border-red-500/20">
              <span className="text-sm font-semibold text-foreground">{m.name}</span>
              <span className="text-xs text-foreground/50">— {m.desc}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Coverage Matrix */}
      <div className="rounded-2xl border border-card-border bg-card p-6">
        <h3 className="text-lg font-semibold mb-1">Capability Coverage</h3>
        <p className="text-sm text-foreground/60 mb-4">What each framework covers — and what only TrustMesh provides end-to-end. <span className="text-foreground/40">Hover a name to learn more.</span></p>
        <div className="-mx-6 px-6 overflow-x-auto pb-2">
          <table className="w-full text-sm border-collapse min-w-[640px]">
            <thead>
              <tr>
                <th className="text-left py-2.5 px-2 border-b border-card-border text-foreground/60 font-medium">Capability</th>
                {fwNames.map((name) => (
                  <th key={name} className={cn("py-2.5 px-2 border-b border-card-border text-center font-medium", name === "TrustMesh" ? "text-accent" : "text-foreground/60")}>
                    {ACRONYMS[name] ? <Tip label={name} desc={ACRONYMS[name]} /> : name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {capabilities.map((cap) => (
                <tr key={cap} className="hover:bg-card-hover/50">
                  <td className="py-2 px-2 border-b border-card-border/50 text-foreground/70">{cap}</td>
                  {fwNames.map((name) => (
                    <td key={name} className="py-2 px-2 border-b border-card-border/50 text-center">
                      {coverage[name]?.has(cap) ? (
                        <span className={name === "TrustMesh" ? "text-accent" : "text-green-400"}>
                          <svg className={cn("inline", name === "TrustMesh" ? "w-4.5 h-4.5" : "w-4 h-4")} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={name === "TrustMesh" ? "3" : "2.5"} strokeLinecap="round" strokeLinejoin="round">
                            <polyline points="20 6 9 17 4 12" />
                          </svg>
                        </span>
                      ) : (
                        <span className="text-foreground/20">—</span>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function ProblemTab() {
  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-xl font-bold mb-1">The Missing Trust Layer</h2>
        <p className="text-sm text-foreground/60">Agents can communicate — but they can&apos;t verify who they&apos;re talking to, what data to share, or log what happened.</p>
      </div>

      {/* Gap diagram */}
      <GapDiagram />

      {/* Multimodal attack callout */}
      <div className="rounded-2xl border border-amber-500/20 bg-amber-500/5 p-5">
        <div className="flex items-center gap-2 mb-2">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-amber-400"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
          <span className="text-sm font-semibold text-amber-400">The Multimodal Blind Spot</span>
        </div>
        <p className="text-sm text-foreground/60 leading-relaxed">
          Current frameworks only handle text. But agents increasingly process <strong className="text-foreground/80">images, audio, documents, and video</strong> — all of which can carry hidden adversarial instructions. A malicious image can hijack an agent&apos;s behavior just as effectively as a text prompt injection. No existing framework addresses this.
        </p>
      </div>

      {/* Scenario comparison */}
      <div className="rounded-2xl border border-card-border bg-card p-6 md:p-8">
        <h3 className="text-lg font-semibold mb-1">The Scenario</h3>
        <p className="text-sm text-foreground/60 mb-5">Bob collapses at a hospital. His doctor needs his medical data. What happens?</p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Without */}
          <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-5">
            <h4 className="text-sm font-semibold text-red-400 mb-3 flex items-center gap-2">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              Without TrustMesh
            </h4>
            <div className="space-y-2.5">
              {[
                "Doctor calls records department",
                "Fax machines, phone trees, manual lookup",
                "30-60 min delay in critical moments",
                "Full record exposed — or nothing at all",
                "No audit trail of who saw what",
                "Bob never knows who accessed his data",
              ].map((text, i) => (
                <div key={i} className="flex gap-2.5 text-sm">
                  <span className="text-red-400/70 shrink-0 font-mono text-xs mt-0.5">{i + 1}</span>
                  <span className="text-foreground/60">{text}</span>
                </div>
              ))}
            </div>
          </div>

          {/* With */}
          <div className="rounded-xl border border-green-500/20 bg-green-500/5 p-5">
            <h4 className="text-sm font-semibold text-green-400 mb-3 flex items-center gap-2">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
              With TrustMesh
            </h4>
            <div className="space-y-2.5">
              {[
                "Hospital issues scoped UCAN token",
                "Bob's agent validates cryptographically",
                "Instant access — under 2 seconds",
                "Only role-appropriate data shared",
                "Full audit log with decision reasoning",
                "Bob gets notification when he recovers",
              ].map((text, i) => (
                <div key={i} className="flex gap-2.5 text-sm">
                  <span className="text-green-400/70 shrink-0 font-mono text-xs mt-0.5">{i + 1}</span>
                  <span className="text-foreground/60">{text}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Impact stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { stat: "4/6", label: "pipeline steps missing", color: "text-red-400" },
          { stat: "0", label: "frameworks scan multimodal", color: "text-red-400" },
          { stat: "0", label: "frameworks audit access", color: "text-red-400" },
          { stat: "1", label: "framework covers all 11", color: "text-accent" },
        ].map((s, i) => (
          <div key={i} className="rounded-xl border border-card-border bg-card p-4 text-center">
            <div className={cn("text-3xl font-bold", s.color)}>{s.stat}</div>
            <div className="text-xs text-foreground/50 mt-1">{s.label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function SolutionTab() {
  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-xl font-bold mb-1">How TrustMesh Solves It</h2>
        <p className="text-sm text-foreground/60">
          TrustMesh doesn&apos;t replace existing frameworks — it <strong className="text-foreground">weaves them together</strong> with the missing trust, encryption, and sovereignty layers.
        </p>
      </div>

      {/* Query protocol flow */}
      <ProtocolFlowDiagram />

      {/* Citadel callout */}
      <CitadelCallout />

      {/* Architecture stack */}
      <div className="rounded-2xl border border-card-border bg-card p-6 md:p-8">
        <h3 className="text-lg font-semibold mb-1">Architecture Stack</h3>
        <p className="text-sm text-foreground/60 mb-5">Each layer builds on the ones below. Existing standards integrated where they fit.</p>

        <div className="space-y-2">
          {[
            { label: "Encrypted Vault", color: "bg-red-500", tech: "AES-256-GCM", desc: "Tiered capsules (private / network / public)", frameworks: [] },
            { label: "Agent Identity", color: "bg-purple-500", tech: "ed25519 + DID", desc: "Cryptographic keypairs per agent", frameworks: ["DID"] },
            { label: "Authorization", color: "bg-amber-500", tech: "UCAN Tokens", desc: "Role-scoped, time-bounded, delegatable", frameworks: ["UCAN"] },
            { label: "Security Scanning", color: "bg-red-500", tech: "Citadel", desc: "Text + multimodal prompt injection & exfil detection", frameworks: [] },
            { label: "Trust Networks", color: "bg-green-500", tech: "Graph scoring", desc: "Connections + shared networks + trust tiers", frameworks: [] },
            { label: "Communication", color: "bg-blue-500", tech: "REST + SSE", desc: "A2A discovery, streaming responses", frameworks: ["A2A", "MCP"] },
            { label: "Audit & Compliance", color: "bg-indigo-500", tech: "Immutable log", desc: "Actor, role, scope, decision for every access", frameworks: [] },
          ].map((layer) => (
            <div key={layer.label} className="flex items-center gap-3 group">
              <div className={cn("w-1.5 h-12 rounded-full shrink-0 opacity-80", layer.color)} />
              <div className="flex-1 flex items-center gap-3 bg-card-hover/20 rounded-xl px-4 py-3 group-hover:bg-card-hover/40 transition-colors">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2.5">
                    <span className="text-sm font-semibold">{layer.label}</span>
                    <span className="text-xs text-foreground/40 font-mono">{layer.tech}</span>
                  </div>
                  <div className="text-sm text-foreground/50">{layer.desc}</div>
                </div>
                {layer.frameworks.length > 0 && (
                  <div className="flex gap-1.5 shrink-0">
                    {layer.frameworks.map((fw) => (
                      <span key={fw} className="px-2.5 py-1 rounded-md bg-card border border-card-border text-xs font-medium text-foreground/60">
                        <Tip label={fw} desc={ACRONYMS[fw] || fw} />
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Emergency access flow */}
      <EmergencyFlowDiagram />

      {/* CTA */}
      <div className="text-center py-8">
        <p className="text-base text-foreground/60 mb-5">Ready to see it in action?</p>
        <div className="flex justify-center gap-3">
          <Link href="/" className="inline-flex items-center gap-2 px-6 py-3 bg-accent hover:bg-accent-hover text-accent-fg font-semibold rounded-xl text-sm transition-all hover:shadow-lg hover:shadow-accent/20">
            Try the Demo
          </Link>
          <Link href="/graph" className="inline-flex items-center gap-2 px-6 py-3 bg-card border border-card-border hover:border-accent/30 text-foreground font-medium rounded-xl text-sm transition-all hover:bg-card-hover">
            View Trust Graph
          </Link>
        </div>
      </div>
    </div>
  );
}

/* ═══════════════ TABS ═══════════════ */

function TabButton({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-all",
        active
          ? "bg-accent text-accent-fg"
          : "text-muted-foreground hover:text-foreground hover:bg-card-hover"
      )}
    >
      {icon}
      {label}
    </button>
  );
}

/* ═══════════════ PAGE ═══════════════ */

export default function AboutPage() {
  const [tab, setTab] = useState<"environment" | "problem" | "solution">("environment");

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <div className="border-b border-card-border">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 py-4 sm:py-6">
          {/* Nav row */}
          <div className="flex items-center justify-end gap-1.5 sm:gap-2 mb-3 sm:mb-4">
            <a href="http://localhost:8100" target="_blank" rel="noopener noreferrer" className="text-xs text-foreground/50 hover:text-foreground transition-colors px-2 sm:px-3 py-1.5 rounded-lg hover:bg-card-hover">Registry</a>
            <Link href="/doc" className="text-xs text-foreground/50 hover:text-foreground transition-colors px-2 sm:px-3 py-1.5 rounded-lg hover:bg-card-hover">Docs</Link>
            <Link href="/" className="text-xs bg-accent text-accent-fg px-3 py-1.5 rounded-lg font-medium hover:bg-accent-hover transition-colors">Demo</Link>
          </div>
          {/* Title */}
          <div className="flex items-center gap-2 mb-2">
            <div className="w-8 h-8 rounded-lg bg-accent flex items-center justify-center shrink-0">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#09090b" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
              </svg>
            </div>
            <h1 className="text-xl sm:text-2xl font-bold">
              Why <span className="text-gradient">TrustMesh</span>?
            </h1>
          </div>
          <p className="text-sm text-foreground/60 max-w-xl">
            AI agents are learning to talk. But they haven&apos;t learned to trust.
          </p>
        </div>
      </div>

      {/* Content */}
      <div className="max-w-5xl mx-auto px-6 py-8">
        {/* Tab bar */}
        <div className="flex gap-1 mb-8 bg-card border border-card-border rounded-xl p-1 w-fit">
          <TabButton
            active={tab === "environment"}
            onClick={() => setTab("environment")}
            icon={<svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>}
            label="Environment"
          />
          <TabButton
            active={tab === "problem"}
            onClick={() => setTab("problem")}
            icon={<svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>}
            label="Problem"
          />
          <TabButton
            active={tab === "solution"}
            onClick={() => setTab("solution")}
            icon={<svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="20 6 9 17 4 12"/></svg>}
            label="Solution"
          />
        </div>

        {/* Tab content */}
        {tab === "environment" && <EnvironmentTab />}
        {tab === "problem" && <ProblemTab />}
        {tab === "solution" && <SolutionTab />}

        {/* Footer */}
        <div className="mt-16 pt-8 border-t border-card-border text-center space-y-1">
          <p className="text-xs text-foreground/40">
            Built with love by <a href="https://github.com/masterfung" target="_blank" rel="noopener noreferrer" className="text-accent hover:text-accent-hover transition-colors">@masterfung</a>
          </p>
          <p className="text-xs text-foreground/40">
            TrustMesh v0.1 &middot; <Link href="/doc" className="text-accent hover:text-accent-hover transition-colors">Docs</Link> &middot; <Link href="/" className="text-accent hover:text-accent-hover transition-colors">Demo</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
