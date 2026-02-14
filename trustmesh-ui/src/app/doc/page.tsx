"use client";

import { useState } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";

/* ═══════════════ NAV SECTIONS ═══════════════ */

const SECTIONS = [
  { id: "what", label: "What is a Pod?" },
  { id: "quickstart", label: "Quick Start" },
  { id: "connect", label: "Connect Pods" },
  { id: "pools", label: "Pools" },
  { id: "layers", label: "Architecture" },
  { id: "agent-card", label: "Agent Card (A2A)" },
  { id: "api", label: "Pod API" },
  { id: "gossip", label: "Cross-Pod Gossip" },
  { id: "security", label: "Security" },
  { id: "protocol", label: "Protocol Spec" },
] as const;

type SectionId = (typeof SECTIONS)[number]["id"];

/* ═══════════════ CODE BLOCK ═══════════════ */

function Code({ children, lang }: { children: string; lang?: string }) {
  return (
    <pre className="rounded-xl bg-[#0a0a1a] border border-card-border p-4 text-[13px] text-foreground/80 overflow-x-auto leading-relaxed font-mono">
      {lang && <div className="text-[10px] text-foreground/30 uppercase tracking-wider mb-2">{lang}</div>}
      <code>{children}</code>
    </pre>
  );
}

function InlineCode({ children }: { children: string }) {
  return <code className="px-1.5 py-0.5 rounded-md bg-card border border-card-border text-[13px] font-mono text-accent">{children}</code>;
}

function H2({ id, children }: { id: string; children: React.ReactNode }) {
  return <h2 id={id} className="text-xl font-bold mt-12 mb-4 pt-6 border-t border-card-border scroll-mt-20">{children}</h2>;
}

function H3({ children }: { children: React.ReactNode }) {
  return <h3 className="text-base font-semibold mt-6 mb-2">{children}</h3>;
}

function P({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-foreground/70 leading-relaxed mb-3">{children}</p>;
}

function Table({ headers, rows }: { headers: string[]; rows: string[][] }) {
  return (
    <div className="overflow-x-auto my-4">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr>
            {headers.map((h) => (
              <th key={h} className="text-left py-2 px-3 border-b border-card-border text-foreground/60 font-medium text-xs">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="hover:bg-card-hover/30">
              {row.map((cell, j) => (
                <td key={j} className={cn("py-2 px-3 border-b border-card-border/50 text-xs", j === 0 ? "font-mono text-accent" : "text-foreground/60")}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Callout({ children, type = "info" }: { children: React.ReactNode; type?: "info" | "warning" | "tip" }) {
  const colors = {
    info: "border-blue-500/30 bg-blue-500/5",
    warning: "border-yellow-500/30 bg-yellow-500/5",
    tip: "border-green-500/30 bg-green-500/5",
  };
  const labels = { info: "Info", warning: "Note", tip: "Tip" };
  return (
    <div className={cn("rounded-xl border p-4 my-4", colors[type])}>
      <p className="text-[10px] font-bold uppercase tracking-wider text-foreground/40 mb-1">{labels[type]}</p>
      <div className="text-sm text-foreground/70 leading-relaxed">{children}</div>
    </div>
  );
}

/* ═══════════════ PAGE ═══════════════ */

export default function DocPage() {
  const [active, setActive] = useState<SectionId>("what");

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <div className="border-b border-card-border sticky top-0 bg-background/95 backdrop-blur-sm z-50">
        <div className="max-w-7xl mx-auto px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-7 h-7 rounded-lg bg-accent flex items-center justify-center">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#09090b" strokeWidth="2.5"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
            </div>
            <span className="font-bold text-sm">TrustMesh</span>
            <span className="text-xs text-foreground/40 font-mono">docs / getting started</span>
          </div>
          <div className="flex items-center gap-2">
            <Link href="/about" className="text-xs text-foreground/50 hover:text-foreground transition-colors px-3 py-1.5 rounded-lg hover:bg-card-hover">Why TrustMesh?</Link>
            <Link href="/" className="text-xs bg-accent text-accent-fg px-3 py-1.5 rounded-lg font-medium hover:bg-accent-hover transition-colors">Demo</Link>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto flex">
        {/* Sidebar nav */}
        <nav className="w-52 shrink-0 sticky top-[53px] h-[calc(100vh-53px)] overflow-y-auto border-r border-card-border py-6 px-4 hidden md:block">
          {SECTIONS.map((s) => (
            <a
              key={s.id}
              href={`#${s.id}`}
              onClick={() => setActive(s.id)}
              className={cn(
                "block px-3 py-1.5 rounded-lg text-xs font-medium transition-colors mb-0.5",
                active === s.id ? "bg-accent/10 text-accent" : "text-foreground/50 hover:text-foreground hover:bg-card-hover"
              )}
            >
              {s.label}
            </a>
          ))}
        </nav>

        {/* Content */}
        <main className="flex-1 min-w-0 px-8 py-8 max-w-4xl">
          {/* What is a Pod? */}
          <div id="what">
            <div className="mb-2">
              <span className="text-[10px] font-bold uppercase tracking-widest text-accent">Getting Started</span>
            </div>
            <h1 className="text-3xl font-bold mb-3">TrustMesh Pods</h1>
            <P>
              A <strong className="text-foreground">pod</strong> is a personal TrustMesh instance. It contains your identity, your AI agent,
              your encrypted vault, and your trust rules. One person = one pod.
            </P>
            <P>
              A pod works <strong className="text-foreground">completely standalone</strong>. No internet required. Chat with your agent,
              store knowledge, manage your vault &mdash; all offline. When you&apos;re ready, connect to other pods.
            </P>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 my-6">
              {[
                { label: "Identity", value: "DID + ed25519", sub: "Self-sovereign" },
                { label: "Agent", value: "Claude Opus 4.6", sub: "Trust-aware AI" },
                { label: "Vault", value: "AES-256-GCM", sub: "Encrypted at rest" },
                { label: "Protocol", value: "A2A + UCAN", sub: "Interoperable" },
              ].map((s) => (
                <div key={s.label} className="rounded-xl border border-card-border bg-card/50 p-3">
                  <p className="text-[10px] text-foreground/40 uppercase tracking-wider">{s.label}</p>
                  <p className="text-sm font-semibold font-mono">{s.value}</p>
                  <p className="text-[11px] text-foreground/50">{s.sub}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Quick Start */}
          <H2 id="quickstart">Run Your Own Pod</H2>
          <P>Three commands to get a pod running:</P>
          <Code lang="bash">{`# 1. Clone and install
git clone https://github.com/trustmesh/trustmesh-core
cd trustmesh-core
uv sync

# 2. Seed demo data (creates users, agents, vault keys)
uv run python -m src.seed

# 3. Start the pod
uv run uvicorn src.main:app --reload --port 8000`}</Code>

          <P>Your pod is now running at <InlineCode>http://localhost:8000</InlineCode>. Check it:</P>
          <Code lang="bash">{`# Pod identity
curl http://localhost:8000/api/pod

# A2A agent card (how other pods find you)
curl http://localhost:8000/.well-known/agent-card.json

# Health check
curl http://localhost:8000/health`}</Code>

          <Callout type="tip">
            <strong>Dev mode:</strong> Use <InlineCode>./dev.sh start</InlineCode> from the repo root to start both backend and frontend automatically.
          </Callout>

          <H3>Environment variables</H3>
          <Table
            headers={["Variable", "Default", "Purpose"]}
            rows={[
              ["TRUSTMESH_POD_NAME", "TrustMesh Pod", "Display name for your pod"],
              ["TRUSTMESH_POD_URL", "http://localhost:8000", "Public URL for federation"],
              ["TRUSTMESH_DB", "./trustmesh.db", "SQLite database path (each pod gets its own)"],
              ["ANTHROPIC_API_KEY", "(required)", "For Claude Opus 4.6 agent responses"],
              ["VOYAGE_API_KEY", "(optional)", "Voyage AI embeddings (falls back to local)"],
            ]}
          />

          {/* Connect Two Pods */}
          <H2 id="connect">Connect Two Pods</H2>
          <P>Federation starts with <strong className="text-foreground">peering</strong> &mdash; two pods that know about each other.</P>

          <H3>1. Start two pods on different ports</H3>
          <Code lang="bash">{`# Terminal 1: Johnson Family Pod
TRUSTMESH_POD_NAME="Johnson Family" \\
TRUSTMESH_POD_URL=http://localhost:8000 \\
TRUSTMESH_DB=./pod_a.db \\
uv run uvicorn src.main:app --port 8000

# Terminal 2: Hospital Pod
TRUSTMESH_POD_NAME="Riverside Hospital" \\
TRUSTMESH_POD_URL=http://localhost:8001 \\
TRUSTMESH_DB=./pod_b.db \\
uv run uvicorn src.main:app --port 8001`}</Code>

          <H3>2. Connect them</H3>
          <Code lang="bash">{`# Pod A connects to Pod B (bidirectional — Pod B learns about Pod A too)
curl -X POST http://localhost:8000/api/pod/peers \\
  -H "Content-Type: application/json" \\
  -d '{"url": "http://localhost:8001"}'

# Verify: Pod B now lists Pod A as a peer
curl http://localhost:8001/api/pod/peers`}</Code>

          <H3>3. Discover agents across federation</H3>
          <Code lang="bash">{`# From Pod A: see all agents (local + remote)
curl http://localhost:8000/api/pod/discover`}</Code>

          <H3>4. Cross-pod query</H3>
          <Code lang="bash">{`# Query a user on Pod B from Pod A
curl -X POST http://localhost:8001/api/pod/query \\
  -H "Content-Type: application/json" \\
  -d '{
    "from_did": "did:key:z6Mk...",
    "from_pod": "http://localhost:8000",
    "to_username": "dr_lee",
    "question": "What services do you provide?"
  }'`}</Code>

          <Callout type="info">
            Cross-pod queries get <strong>public trust level</strong> by default &mdash; only &ldquo;open&rdquo; capsules are visible.
            To access internal data, create a connection between users across pods.
          </Callout>

          <Callout type="tip">
            Run the full demo script: <InlineCode>uv run python demo_federation.py</InlineCode>
          </Callout>

          {/* Pools */}
          <H2 id="pools">Pools (Group Trust)</H2>
          <P>
            A <strong className="text-foreground">pool</strong> is a group of pods that trust each other. It maps to TrustMesh&apos;s
            Network concept, but spanning multiple pods.
          </P>

          <Table
            headers={["Pool Example", "Members", "Data Shared"]}
            rows={[
              ["Johnson Family", "Peter, Molly, Jane, Bill (each on their own pod)", "Health, schedules, home info"],
              ["Rose's Care Circle", "Rose, Molly, Dorothy, Dr. Patel", "Health data, medication schedules"],
              ["TechCorp PM Team", "Molly, Kyle", "Work projects, deadlines"],
            ]}
          />

          <P>How pools work:</P>
          <ul className="list-disc list-inside text-sm text-foreground/70 space-y-1 mb-3 ml-2">
            <li>One pod owner creates the pool (becomes admin)</li>
            <li>Others join via invite link</li>
            <li>Each pod retains full sovereignty &mdash; the pool doesn&apos;t control your pod</li>
            <li>Pool members automatically get &ldquo;internal&rdquo; visibility on relevant capsules</li>
            <li>Pool governance inherits from each pod&apos;s individual settings</li>
          </ul>

          {/* Architecture */}
          <H2 id="layers">The 5 Layers</H2>
          <P>TrustMesh federation has 5 layers, each independent and composable:</P>

          <Table
            headers={["Layer", "Name", "What It Does", "Status"]}
            rows={[
              ["1", "Pod", "One person = one pod. Standalone, works offline.", "Built"],
              ["2", "Peering", "Two pods directly connected. Bidirectional trust.", "Built"],
              ["3", "Pools", "Group of pods sharing trust. Maps to Networks.", "Built (single-pod)"],
              ["4", "Registry", "Optional public discoverability. Phone book for agents.", "Design"],
              ["5", "Open Federation", "A2A-compatible. Any agent can talk to your pod.", "Built (agent card)"],
            ]}
          />

          <H3>Trust flows through layers</H3>
          <Code lang="text">{`Layer 1: Pod works alone. Private vault, local agent.
    |
Layer 2: Peer with someone. They see your "open" capsules.
    |
Layer 3: Join a pool together. Now they see "internal" capsules.
    |
Layer 4: Register publicly. Anyone can find your agent.
    |
Layer 5: A2A agent card. Any compatible agent can connect.`}</Code>

          {/* Agent Card */}
          <H2 id="agent-card">A2A Agent Card</H2>
          <P>
            Every pod publishes an <strong className="text-foreground">A2A-compatible agent card</strong> at{" "}
            <InlineCode>/.well-known/agent-card.json</InlineCode>. This is how other pods (and any A2A-compatible agent) discover you.
          </P>

          <Code lang="json">{`{
  "name": "Johnson Family Pod Agent",
  "description": "TrustMesh pod agent for Johnson Family Pod",
  "url": "http://localhost:8000/api/pod/a2a",
  "version": "0.1.0",
  "capabilities": {
    "streaming": false,
    "pushNotifications": false
  },
  "authentication": {
    "schemes": ["ucan", "session"]
  },
  "skills": [
    {
      "id": "agent-peter",
      "name": "Peter Johnson's Knowledge",
      "description": "Query Peter Johnson's shared knowledge (trust-level dependent)"
    },
    {
      "id": "agent-molly",
      "name": "Molly Johnson's Knowledge",
      "description": "Query Molly Johnson's shared knowledge (trust-level dependent)"
    }
  ],
  "defaultInputModes": ["text"],
  "defaultOutputModes": ["text"],
  "trustmesh": {
    "pod_name": "Johnson Family Pod",
    "pod_url": "http://localhost:8000",
    "protocol": "trustmesh/0.1",
    "did": "did:key:z6Mk...",
    "public_key_b64": "..."
  }
}`}</Code>

          <P>
            The <InlineCode>trustmesh</InlineCode> extension contains TrustMesh-specific metadata. Standard A2A clients
            can ignore it and still discover the agent via the standard fields.
          </P>

          {/* API Reference */}
          <H2 id="api">Pod API Reference</H2>

          <H3>Pod Identity</H3>
          <Table
            headers={["Method", "Endpoint", "Auth", "Description"]}
            rows={[
              ["GET", "/api/pod", "None", "This pod's identity, agents, and status (public info)"],
              ["GET", "/.well-known/agent-card.json", "None", "A2A-compatible agent card for discovery"],
              ["GET", "/health", "None", "Health check"],
            ]}
          />

          <H3>Peer Management</H3>
          <Table
            headers={["Method", "Endpoint", "Auth", "Description"]}
            rows={[
              ["GET", "/api/pod/peers", "None", "List all connected peer pods"],
              ["POST", "/api/pod/peers", "None", "Connect to a peer pod (bidirectional)"],
              ["DELETE", "/api/pod/peers/{id}", "None", "Disconnect from a peer pod"],
              ["POST", "/api/pod/peers/{id}/ping", "None", "Health check a specific peer"],
            ]}
          />

          <H3>Cross-Pod</H3>
          <Table
            headers={["Method", "Endpoint", "Auth", "Description"]}
            rows={[
              ["GET", "/api/pod/discover", "None", "Discover agents across all connected peers"],
              ["POST", "/api/pod/query", "None", "Receive incoming cross-pod gossip query"],
            ]}
          />

          <H3>Core API (unchanged)</H3>
          <Table
            headers={["Category", "Key Endpoints"]}
            rows={[
              ["Auth", "POST /api/auth/login, POST /api/auth/logout, GET /api/auth/me"],
              ["Capsules", "GET /api/users/{id}/capsules, POST /api/users/{id}/capsules"],
              ["Queries", "POST /api/query, POST /api/query/stream"],
              ["Networks", "POST /api/networks, GET /api/users/{id}/networks"],
              ["Emergency", "POST /api/emergency/token, POST /api/emergency/access"],
              ["FHIR", "GET /api/users/{id}/fhir/Patient, GET /api/users/{id}/fhir/Bundle"],
              ["Audit", "GET /api/users/{id}/audit"],
              ["PIN", "POST /api/users/{id}/pin, POST /api/users/{id}/pin/verify"],
            ]}
          />

          {/* Cross-Pod Gossip */}
          <H2 id="gossip">Cross-Pod Gossip</H2>
          <P>When a remote pod sends a query, the target pod runs its gossip pipeline with restrictions:</P>

          <Code lang="text">{`Remote Agent (Pod A) → query → Target Agent (Pod B)

Pod B pipeline:
  1. IDENTIFY      Look up target user locally
  2. TRUST RESOLVE Remote agent → "public" trust level (default)
                   Unless remote agent has a local connection → normal trust
  3. CITADEL IN    Scan incoming question for threats
  4. CAPSULE FILTER Only "open" visibility capsules (public trust)
  5. SEMANTIC SEARCH Match question against permitted capsules
  6. LLM GENERATE  Claude responds from permitted data only
  7. CITADEL OUT   Scan response for data leaks
  8. AUDIT LOG     Record: remote DID, source pod, trust level, decision
  9. RETURN        Send response back to Pod A`}</Code>

          <Callout type="warning">
            Remote queries are <strong>read-only</strong>. No tools (save, update, query peers) are available.
            The remote agent can only read from open capsules.
          </Callout>

          {/* Security */}
          <H2 id="security">Security Model</H2>
          <P>Every cross-pod exchange is security-scanned and audit-logged:</P>

          <Table
            headers={["Threat", "Mitigation"]}
            rows={[
              ["Malicious remote query", "Citadel input scanning (prompt injection, jailbreak detection)"],
              ["Data exfiltration", "Citadel output scanning + public trust level (only open capsules)"],
              ["Impersonation", "ed25519 DID verification (future: signed HTTP requests)"],
              ["Rogue peer pod", "Trust level controls what data is accessible. Default: public only."],
              ["Flood / DoS", "Rate limiting per source agent, scaling with trust level"],
              ["Audit evasion", "Immutable audit log with remote DID, source pod, and decision"],
            ]}
          />

          <H3>Trust escalation</H3>
          <P>Trust is earned progressively:</P>
          <Code lang="text">{`Unknown agent → "public" trust → sees only open capsules
    |
Peered pods → still "public" → needs user-level connection
    |
User connection created → "network" trust → sees internal capsules
    |
Pool membership → "network" trust → sees pool-scoped capsules
    |
Emergency UCAN token → bypasses trust → role-scoped, time-bounded`}</Code>

          {/* Protocol Spec */}
          <H2 id="protocol">Protocol Specification</H2>
          <P>For the full protocol specification including encryption details, UCAN tokens, and compliance mapping,
            see the protocol reference:</P>

          <Table
            headers={["Layer", "Standard", "Purpose"]}
            rows={[
              ["Identity", "W3C DID + ed25519", "Self-sovereign agent identity"],
              ["Vault", "AES-256-GCM + Argon2id", "Encrypted capsule storage"],
              ["Authorization", "UCAN v0.10", "Scoped, time-bounded access tokens"],
              ["Gossip", "TrustMesh v0.1", "Trust-resolved cross-agent queries"],
              ["Discovery", "A2A + .well-known", "Agent card publication and peer discovery"],
              ["Audit", "Immutable log", "Every access recorded with full provenance"],
            ]}
          />

          <H3>Standards we build on</H3>
          <Table
            headers={["Standard", "What it does", "TrustMesh use"]}
            rows={[
              ["A2A Protocol", "Agent-to-agent messaging (Google/LF)", "Agent card format, cross-pod messaging"],
              ["did:key", "Self-certifying identity from public key", "Agent identity (W3C standard)"],
              ["UCAN", "Offline-first capability delegation", "Emergency access tokens"],
              ["MCP", "Agent-to-tool connections", "Future: register agents in MCP registry"],
              ["FHIR R4", "Healthcare data interoperability", "Health data export"],
              ["W3C VC 2.0", "Verifiable credentials", "Future: trust assertions"],
            ]}
          />

          {/* Footer */}
          <div className="mt-16 pt-8 border-t border-card-border text-center">
            <p className="text-xs text-foreground/40">
              TrustMesh v0.1 &middot; <Link href="/" className="text-accent hover:text-accent-hover transition-colors">Demo</Link> &middot; <Link href="/about" className="text-accent hover:text-accent-hover transition-colors">Why TrustMesh?</Link>
            </p>
          </div>
        </main>
      </div>
    </div>
  );
}
