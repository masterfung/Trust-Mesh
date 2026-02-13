"use client";

import Link from "next/link";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/* ─────────────── Data ─────────────── */

type Framework = {
  name: string;
  fullName: string;
  by: string;
  color: string;
  layer: string;
  what: string;
  brings: string[];
  missing: string[];
};

const FRAMEWORKS: Framework[] = [
  {
    name: "A2A",
    fullName: "Agent-to-Agent Protocol",
    by: "Google DeepMind",
    color: "from-blue-500 to-cyan-400",
    layer: "Communication",
    what: "Standardized protocol for AI agents to discover, authenticate, and communicate with each other.",
    brings: ["Agent discovery", "Task delegation", "Interoperability"],
    missing: ["No trust model", "No data sovereignty", "No scoped authorization"],
  },
  {
    name: "MCP",
    fullName: "Model Context Protocol",
    by: "Anthropic",
    color: "from-orange-500 to-amber-400",
    layer: "Context",
    what: "Universal protocol for connecting AI models to tools, data sources, and external services.",
    brings: ["Tool integration", "Context management", "Standardized resources"],
    missing: ["No peer trust", "No encryption", "No identity layer"],
  },
  {
    name: "UCP",
    fullName: "Universal Context Protocol",
    by: "Google",
    color: "from-green-500 to-emerald-400",
    layer: "Context",
    what: "Google's approach to connecting AI models with structured context from enterprise data sources.",
    brings: ["Enterprise integration", "Structured context", "Multi-modal support"],
    missing: ["Vendor-centric", "No decentralized identity", "No user sovereignty"],
  },
  {
    name: "x402",
    fullName: "HTTP 402 Payment Protocol",
    by: "Coinbase",
    color: "from-indigo-500 to-violet-400",
    layer: "Payment",
    what: "Native payment protocol for agent-to-agent transactions using HTTP 402 status codes.",
    brings: ["Agent payments", "Micropayments", "Service monetization"],
    missing: ["Payment only", "No trust verification", "No knowledge sharing"],
  },
  {
    name: "DID",
    fullName: "Decentralized Identifiers",
    by: "W3C Standard",
    color: "from-purple-500 to-pink-400",
    layer: "Identity",
    what: "Self-sovereign identity standard enabling verifiable, decentralized digital identifiers.",
    brings: ["Self-sovereign ID", "Verifiable credentials", "No central authority"],
    missing: ["Identity only", "No authorization logic", "No agent integration"],
  },
  {
    name: "UCAN",
    fullName: "User Controlled Auth Networks",
    by: "Fission / UCAN WG",
    color: "from-amber-500 to-yellow-400",
    layer: "Authorization",
    what: "Capability-based authorization using cryptographic tokens that users can delegate and attenuate.",
    brings: ["Scoped permissions", "Delegatable tokens", "Time-bounded access"],
    missing: ["Auth only", "No data layer", "No agent orchestration"],
  },
  {
    name: "OpenCLAAS",
    fullName: "Open Competitive Landscape for Agents and Services",
    by: "Community",
    color: "from-rose-500 to-red-400",
    layer: "Discovery",
    what: "Open marketplace and discovery layer for AI agent services and capabilities.",
    brings: ["Agent marketplace", "Competitive pricing", "Service discovery"],
    missing: ["No trust verification", "No encryption", "No knowledge management"],
  },
];

const LAYER_ORDER = ["Identity", "Authorization", "Communication", "Context", "Payment", "Discovery"];

const PROBLEMS = [
  {
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
        <line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
      </svg>
    ),
    title: "The Trust Gap",
    description: "Agents can talk to each other (A2A), but have no way to verify trust. A doctor's agent asking for patient data looks identical to a stranger's agent.",
    detail: "Current protocols handle transport, not trust. There's no mechanism to say 'I trust this agent because it belongs to someone in my family network' vs 'this is a random public request'.",
    severity: "critical",
  },
  {
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="11" width="18" height="11" rx="2" ry="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" />
      </svg>
    ),
    title: "No Data Sovereignty",
    description: "Your knowledge, preferences, and private data live on corporate servers. You don't control who accesses what, or when.",
    detail: "MCP and UCP connect AI to data sources, but the user isn't in the loop. There's no encrypted vault, no tiered access, no user-controlled sharing policies.",
    severity: "critical",
  },
  {
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" /><path d="M2 12h20" /><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
      </svg>
    ),
    title: "All-or-Nothing Access",
    description: "When sharing does happen, it's binary: share everything or share nothing. No role-based, context-aware, time-bounded access.",
    detail: "A paramedic doesn't need your full medical history — just blood type and allergies. Current systems can't express 'share only medications for the next 2 hours'.",
    severity: "high",
  },
  {
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" />
        <line x1="9" y1="15" x2="15" y2="15" />
      </svg>
    ),
    title: "No Audit Trail",
    description: "When someone accesses your data via an AI agent, there's no immutable record. You don't know who accessed what, when, or why.",
    detail: "HIPAA and GDPR require audit trails. Current agent frameworks have no built-in logging of who accessed what data through which authorization.",
    severity: "high",
  },
  {
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" />
        <line x1="1" y1="1" x2="23" y2="23" />
      </svg>
    ),
    title: "Fragmented Identity",
    description: "DIDs exist as a standard, but no agent framework integrates them. Each platform has its own identity silo.",
    detail: "You can't prove your agent represents you across different platforms. There's no unified cryptographic identity linking your agent to your real-world trust relationships.",
    severity: "medium",
  },
];

type SolutionLayer = {
  label: string;
  color: string;
  frameworks: string[];
  trustmesh: string;
};

const SOLUTION_LAYERS: SolutionLayer[] = [
  { label: "Encrypted Vault", color: "bg-red-500", frameworks: [], trustmesh: "AES-256-GCM encrypted capsules with tiered access (private/network/public)" },
  { label: "Agent Identity", color: "bg-purple-500", frameworks: ["DID"], trustmesh: "Ed25519 keypairs + DID per agent, published via A2A discovery" },
  { label: "Authorization", color: "bg-amber-500", frameworks: ["UCAN"], trustmesh: "Role-scoped, time-bounded UCAN tokens with ed25519 signatures" },
  { label: "Trust Networks", color: "bg-green-500", frameworks: [], trustmesh: "Multi-hop trust scoring via shared networks, connections, and Citadel scanning" },
  { label: "Communication", color: "bg-blue-500", frameworks: ["A2A", "MCP"], trustmesh: "A2A protocol discovery + MCP-compatible tool integration" },
  { label: "Audit & Compliance", color: "bg-indigo-500", frameworks: [], trustmesh: "Immutable audit trail with actor, role, scope, and decision for every access" },
];

const EMERGENCY_STEPS = [
  { actor: "Hospital", action: "Issues UCAN token", detail: "Scoped to attending_physician role, 2-hour expiry, signed with hospital's ed25519 key", color: "text-amber-400" },
  { actor: "Bob's Agent", action: "Validates token", detail: "Verifies signature, checks expiry, confirms audience DID matches, validates issuer is registered", color: "text-blue-400" },
  { actor: "Bob's Agent", action: "Filters by scope", detail: "attending_physician role grants access to: medications, allergies, conditions, history. NOT finances.", color: "text-green-400" },
  { actor: "System", action: "Logs everything", detail: "Audit entry: who accessed, what role, which capsules, decision, timestamp. Notification queued for Bob.", color: "text-purple-400" },
  { actor: "Bob", action: "Reviews access", detail: "When he recovers, Bob sees: 'Riverside Hospital accessed your medical data via emergency protocol at 2:34 AM'", color: "text-cyan-400" },
];

/* ─────────────── Components ─────────────── */

function FrameworkCard({ fw }: { fw: Framework }) {
  return (
    <Card className="bg-card border-card-border hover:border-accent/20 transition-all">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className={cn("w-8 h-8 rounded-lg bg-gradient-to-br flex items-center justify-center text-white text-xs font-bold", fw.color)}>
              {fw.name[0]}
            </div>
            <div>
              <CardTitle className="text-sm">{fw.name}</CardTitle>
              <CardDescription className="text-[10px]">{fw.by}</CardDescription>
            </div>
          </div>
          <Badge variant="outline" className="text-[10px]">{fw.layer}</Badge>
        </div>
      </CardHeader>
      <CardContent className="pt-0 space-y-3">
        <p className="text-xs text-muted-foreground leading-relaxed">{fw.what}</p>
        <div>
          <p className="text-[10px] font-semibold text-green-400 mb-1">What it brings</p>
          <div className="flex flex-wrap gap-1">
            {fw.brings.map((b) => (
              <Badge key={b} variant="secondary" className="text-[10px] bg-green-500/10 text-green-400 border-green-500/20">
                {b}
              </Badge>
            ))}
          </div>
        </div>
        <div>
          <p className="text-[10px] font-semibold text-red-400 mb-1">What&apos;s missing</p>
          <div className="flex flex-wrap gap-1">
            {fw.missing.map((m) => (
              <Badge key={m} variant="secondary" className="text-[10px] bg-red-500/10 text-red-400 border-red-500/20">
                {m}
              </Badge>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function CoverageMatrix() {
  const capabilities = [
    "Agent Discovery",
    "Agent Communication",
    "Tool Integration",
    "Identity (DID)",
    "Authorization",
    "Encryption",
    "Trust Scoring",
    "Data Sovereignty",
    "Audit Trail",
    "Scoped Access",
  ];
  const coverage: Record<string, Set<string>> = {
    "A2A":       new Set(["Agent Discovery", "Agent Communication"]),
    "MCP":       new Set(["Tool Integration", "Agent Communication"]),
    "UCP":       new Set(["Tool Integration"]),
    "x402":      new Set([]),
    "DID":       new Set(["Identity (DID)"]),
    "UCAN":      new Set(["Authorization", "Scoped Access"]),
    "OpenCLAAS": new Set(["Agent Discovery"]),
    "TrustMesh": new Set(capabilities), // all of them
  };
  const fwNames = ["A2A", "MCP", "UCP", "x402", "DID", "UCAN", "OpenCLAAS", "TrustMesh"];

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr>
            <th className="text-left py-2 px-2 border-b border-card-border text-muted-foreground font-medium">Capability</th>
            {fwNames.map((name) => (
              <th key={name} className={cn(
                "py-2 px-2 border-b border-card-border text-center font-medium",
                name === "TrustMesh" ? "text-accent" : "text-muted-foreground"
              )}>
                {name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {capabilities.map((cap) => (
            <tr key={cap} className="hover:bg-card-hover/50">
              <td className="py-1.5 px-2 border-b border-card-border/50 text-foreground/80">{cap}</td>
              {fwNames.map((name) => (
                <td key={name} className="py-1.5 px-2 border-b border-card-border/50 text-center">
                  {coverage[name]?.has(cap) ? (
                    <span className={name === "TrustMesh" ? "text-accent" : "text-green-400"}>
                      {name === "TrustMesh" ? (
                        <svg className="inline w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                          <polyline points="20 6 9 17 4 12" />
                        </svg>
                      ) : (
                        <svg className="inline w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                          <polyline points="20 6 9 17 4 12" />
                        </svg>
                      )}
                    </span>
                  ) : (
                    <span className="text-muted-foreground/50">—</span>
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ArchitectureDiagram() {
  return (
    <div className="relative">
      {/* Layer stack */}
      <div className="space-y-2">
        {SOLUTION_LAYERS.map((layer, i) => (
          <div key={layer.label} className="flex items-stretch gap-3">
            {/* Layer bar */}
            <div className={cn("w-1.5 rounded-full shrink-0", layer.color)} />
            <div className="flex-1 bg-card border border-card-border rounded-xl p-4 hover:border-accent/20 transition-all">
              <div className="flex items-center justify-between mb-1">
                <h4 className="text-sm font-semibold">{layer.label}</h4>
                {layer.frameworks.length > 0 && (
                  <div className="flex gap-1">
                    {layer.frameworks.map((fw) => (
                      <Badge key={fw} variant="outline" className="text-[10px]">{fw}</Badge>
                    ))}
                  </div>
                )}
              </div>
              <p className="text-xs text-muted-foreground">{layer.trustmesh}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function EmergencyFlowDiagram() {
  return (
    <div className="space-y-3">
      {EMERGENCY_STEPS.map((step, i) => (
        <div key={i} className="flex gap-3">
          {/* Step number + connector */}
          <div className="flex flex-col items-center">
            <div className="w-7 h-7 rounded-full bg-card border border-card-border flex items-center justify-center text-xs font-bold text-foreground/80">
              {i + 1}
            </div>
            {i < EMERGENCY_STEPS.length - 1 && (
              <div className="w-px flex-1 bg-card-border my-1" />
            )}
          </div>
          {/* Content */}
          <div className="flex-1 pb-3">
            <div className="flex items-center gap-2 mb-0.5">
              <span className={cn("text-xs font-bold", step.color)}>{step.actor}</span>
              <span className="text-xs text-foreground font-medium">{step.action}</span>
            </div>
            <p className="text-xs text-muted-foreground leading-relaxed">{step.detail}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

function SeverityBadge({ severity }: { severity: string }) {
  const styles: Record<string, string> = {
    critical: "bg-red-500/10 text-red-400 border-red-500/20",
    high: "bg-amber-500/10 text-amber-400 border-amber-500/20",
    medium: "bg-blue-500/10 text-blue-400 border-blue-500/20",
  };
  return <Badge variant="outline" className={cn("text-[10px] uppercase", styles[severity])}>{severity}</Badge>;
}

/* ─────────────── Page ─────────────── */

export default function AboutPage() {
  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <div className="border-b border-card-border">
        <div className="max-w-5xl mx-auto px-6 py-6">
          <div className="flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2 mb-2">
                <div className="w-8 h-8 rounded-lg bg-accent flex items-center justify-center">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#09090b" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                  </svg>
                </div>
                <h1 className="text-2xl font-bold">
                  Why <span className="text-gradient">TrustMesh</span>?
                </h1>
              </div>
              <p className="text-sm text-muted-foreground max-w-xl">
                AI agents are learning to talk. But they haven&apos;t learned to trust. Here&apos;s why that matters and how TrustMesh solves it.
              </p>
            </div>
            <Link
              href="/"
              className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-card border border-card-border rounded-xl hover:border-accent/30 hover:bg-card-hover transition-all text-muted-foreground hover:text-foreground"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="19" y1="12" x2="5" y2="12" />
                <polyline points="12 19 5 12 12 5" />
              </svg>
              Back
            </Link>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="max-w-5xl mx-auto px-6 py-8">
        <Tabs defaultValue="environment" className="w-full">
          <TabsList className="mb-8 bg-card border border-card-border rounded-xl p-1">
            <TabsTrigger value="environment" className="rounded-lg data-[state=active]:bg-accent data-[state=active]:text-accent-fg">
              <svg className="w-3.5 h-3.5 mr-1.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" /><path d="M2 12h20" /><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
              </svg>
              Environment
            </TabsTrigger>
            <TabsTrigger value="problem" className="rounded-lg data-[state=active]:bg-accent data-[state=active]:text-accent-fg">
              <svg className="w-3.5 h-3.5 mr-1.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
              </svg>
              Problem
            </TabsTrigger>
            <TabsTrigger value="solution" className="rounded-lg data-[state=active]:bg-accent data-[state=active]:text-accent-fg">
              <svg className="w-3.5 h-3.5 mr-1.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="20 6 9 17 4 12" />
              </svg>
              Solution
            </TabsTrigger>
          </TabsList>

          {/* ── Environment Tab ── */}
          <TabsContent value="environment" className="space-y-8">
            <div>
              <h2 className="text-lg font-bold mb-1">The Agent Framework Landscape</h2>
              <p className="text-sm text-muted-foreground mb-6">
                Seven major frameworks are shaping how AI agents interact. Each solves a piece of the puzzle — but none solves the whole thing.
              </p>

              {/* Layer legend */}
              <div className="flex flex-wrap gap-2 mb-6">
                {LAYER_ORDER.map((layer) => (
                  <Badge key={layer} variant="outline" className="text-xs">{layer}</Badge>
                ))}
              </div>

              {/* Framework cards grid */}
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
                {FRAMEWORKS.map((fw) => (
                  <FrameworkCard key={fw.name} fw={fw} />
                ))}
              </div>
            </div>

            {/* Coverage Matrix */}
            <Card className="bg-card border-card-border">
              <CardHeader>
                <CardTitle className="text-base">Capability Coverage Matrix</CardTitle>
                <CardDescription>
                  How each framework contributes — and what only TrustMesh provides end-to-end.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <CoverageMatrix />
              </CardContent>
            </Card>
          </TabsContent>

          {/* ── Problem Tab ── */}
          <TabsContent value="problem" className="space-y-8">
            <div>
              <h2 className="text-lg font-bold mb-1">What&apos;s Missing</h2>
              <p className="text-sm text-muted-foreground mb-6">
                The current agent ecosystem has critical gaps. No framework addresses the fundamental question: <strong className="text-foreground">how do agents trust each other with your private data?</strong>
              </p>
            </div>

            {/* Problem cards */}
            <div className="space-y-4">
              {PROBLEMS.map((p) => (
                <Card key={p.title} className="bg-card border-card-border hover:border-accent/20 transition-all">
                  <CardContent className="pt-6">
                    <div className="flex gap-4">
                      <div className="text-muted-foreground shrink-0 mt-0.5">{p.icon}</div>
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-2">
                          <h3 className="text-base font-semibold">{p.title}</h3>
                          <SeverityBadge severity={p.severity} />
                        </div>
                        <p className="text-sm text-muted-foreground mb-2">{p.description}</p>
                        <p className="text-xs text-muted-foreground/80 leading-relaxed">{p.detail}</p>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>

            {/* Visual: The Gap Diagram */}
            <Card className="bg-card border-card-border">
              <CardHeader>
                <CardTitle className="text-base">The Scenario</CardTitle>
                <CardDescription>Bob collapses at a hospital. His doctor needs his medical data. What happens today?</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {/* Without TrustMesh */}
                  <div className="p-4 rounded-xl border border-red-500/20 bg-red-500/5">
                    <h4 className="text-sm font-semibold text-red-400 mb-3 flex items-center gap-2">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
                      </svg>
                      Without TrustMesh
                    </h4>
                    <ul className="space-y-2 text-xs text-muted-foreground">
                      <li className="flex gap-2"><span className="text-red-400 shrink-0">1.</span> Doctor calls records department</li>
                      <li className="flex gap-2"><span className="text-red-400 shrink-0">2.</span> Fax machines, phone trees, manual lookup</li>
                      <li className="flex gap-2"><span className="text-red-400 shrink-0">3.</span> 30-60 min delay in critical moments</li>
                      <li className="flex gap-2"><span className="text-red-400 shrink-0">4.</span> Full record exposed or nothing at all</li>
                      <li className="flex gap-2"><span className="text-red-400 shrink-0">5.</span> No audit trail of who saw what</li>
                      <li className="flex gap-2"><span className="text-red-400 shrink-0">6.</span> Bob never knows who accessed his data</li>
                    </ul>
                  </div>

                  {/* With TrustMesh */}
                  <div className="p-4 rounded-xl border border-green-500/20 bg-green-500/5">
                    <h4 className="text-sm font-semibold text-green-400 mb-3 flex items-center gap-2">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                      With TrustMesh
                    </h4>
                    <ul className="space-y-2 text-xs text-muted-foreground">
                      <li className="flex gap-2"><span className="text-green-400 shrink-0">1.</span> Hospital issues scoped UCAN token</li>
                      <li className="flex gap-2"><span className="text-green-400 shrink-0">2.</span> Bob&apos;s agent validates cryptographically</li>
                      <li className="flex gap-2"><span className="text-green-400 shrink-0">3.</span> Instant access — under 2 seconds</li>
                      <li className="flex gap-2"><span className="text-green-400 shrink-0">4.</span> Only role-appropriate data shared</li>
                      <li className="flex gap-2"><span className="text-green-400 shrink-0">5.</span> Full audit log with decision reasoning</li>
                      <li className="flex gap-2"><span className="text-green-400 shrink-0">6.</span> Bob gets notification when he recovers</li>
                    </ul>
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* ── Solution Tab ── */}
          <TabsContent value="solution" className="space-y-8">
            <div>
              <h2 className="text-lg font-bold mb-1">How TrustMesh Solves It</h2>
              <p className="text-sm text-muted-foreground mb-6">
                TrustMesh doesn&apos;t replace existing frameworks — it <strong className="text-foreground">weaves them together</strong> with the missing trust and sovereignty layers.
              </p>
            </div>

            {/* Architecture Stack */}
            <Card className="bg-card border-card-border">
              <CardHeader>
                <CardTitle className="text-base">Architecture Stack</CardTitle>
                <CardDescription>Each layer builds on the ones below. Existing standards are integrated where they fit.</CardDescription>
              </CardHeader>
              <CardContent>
                <ArchitectureDiagram />
              </CardContent>
            </Card>

            {/* Emergency Access Flow */}
            <Card className="bg-card border-card-border">
              <CardHeader>
                <CardTitle className="text-base">Emergency Access Flow</CardTitle>
                <CardDescription>Real-world example: hospital needs a patient&apos;s medical data via UCAN token.</CardDescription>
              </CardHeader>
              <CardContent>
                <EmergencyFlowDiagram />
              </CardContent>
            </Card>

            {/* Key innovations */}
            <div>
              <h3 className="text-base font-semibold mb-4">Key Innovations</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {[
                  {
                    title: "Trust-Tiered Knowledge Capsules",
                    description: "Knowledge stored in encrypted capsules with three tiers: private (only you), network (shared groups), and public (everyone). Each capsule has freshness tracking, category tags, and context modes.",
                    icon: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>,
                  },
                  {
                    title: "Citadel Security Scanning",
                    description: "Every query passes through Citadel — an LLM-based security scanner that detects prompt injection, data exfiltration attempts, and unsafe content before any data is shared.",
                    icon: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>,
                  },
                  {
                    title: "Proactive AI Agents",
                    description: "Each user gets a personal AI agent (Claude Opus 4.6) that manages their vault, generates briefings, handles queries, and acts on their behalf — all within their trust policies.",
                    icon: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="12" cy="12" r="3"/><path d="M12 1v2m0 18v2M4.22 4.22l1.42 1.42m12.72 12.72l1.42 1.42M1 12h2m18 0h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>,
                  },
                  {
                    title: "Cryptographic Emergency Access",
                    description: "UCAN tokens signed with ed25519 enable role-scoped, time-bounded emergency access. A paramedic sees blood type; a doctor sees full history. Every access is audited.",
                    icon: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>,
                  },
                ].map((item) => (
                  <Card key={item.title} className="bg-card border-card-border">
                    <CardContent className="pt-6">
                      <div className="flex items-start gap-3">
                        <div className="text-accent shrink-0 mt-0.5">{item.icon}</div>
                        <div>
                          <h4 className="text-sm font-semibold mb-1">{item.title}</h4>
                          <p className="text-xs text-muted-foreground leading-relaxed">{item.description}</p>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </div>

            {/* CTA */}
            <div className="text-center py-8">
              <p className="text-sm text-muted-foreground mb-4">
                Ready to see it in action?
              </p>
              <div className="flex justify-center gap-3">
                <Link
                  href="/"
                  className="inline-flex items-center gap-2 px-6 py-3 bg-accent hover:bg-accent-hover text-accent-fg font-semibold rounded-xl text-sm transition-all hover:shadow-lg hover:shadow-accent/20"
                >
                  Try the Demo
                </Link>
                <Link
                  href="/graph"
                  className="inline-flex items-center gap-2 px-6 py-3 bg-card border border-card-border hover:border-accent/30 text-foreground font-medium rounded-xl text-sm transition-all hover:bg-card-hover"
                >
                  View Trust Graph
                </Link>
              </div>
            </div>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
