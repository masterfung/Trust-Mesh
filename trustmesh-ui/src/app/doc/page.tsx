"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";

/* ═══════════════ NAV SECTIONS ═══════════════ */

const SECTIONS = [
  // Basics
  { id: "what", label: "What is TrustMesh?", group: "Basics" },
  { id: "quickstart", label: "Quick Start", group: "Basics" },
  { id: "cli", label: "CLI & MCP", group: "Basics" },
  // Concepts
  { id: "trust", label: "Trust Levels", group: "Concepts" },
  { id: "pools", label: "Pools", group: "Concepts" },
  { id: "connections", label: "Connections", group: "Concepts" },
  { id: "confidential", label: "Confidential AI", group: "Concepts" },
  // Federation
  { id: "connect", label: "Connect Pods", group: "Federation" },
  { id: "layers", label: "Architecture", group: "Federation" },
  { id: "agent-card", label: "Agent Card", group: "Federation" },
  { id: "registry", label: "Public Registry", group: "Federation" },
  // Reference
  { id: "api", label: "Pod API", group: "Reference" },
  { id: "gossip", label: "Cross-Pod Gossip", group: "Reference" },
  { id: "security", label: "Security", group: "Reference" },
  { id: "protocol", label: "Protocol Spec", group: "Reference" },
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
  return <h2 id={id} className="text-xl font-bold mt-20 mb-6 pt-8 border-t border-card-border scroll-mt-20">{children}</h2>;
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
  const ticking = useRef(false);

  const updateActive = useCallback(() => {
    const ids = SECTIONS.map((s) => s.id);
    const offset = 120; // account for sticky header + some breathing room

    // If scrolled to bottom, activate the last section
    const atBottom = window.innerHeight + window.scrollY >= document.body.scrollHeight - 40;
    if (atBottom) {
      setActive(ids[ids.length - 1] as SectionId);
      ticking.current = false;
      return;
    }

    let current: SectionId = "what";
    for (const id of ids) {
      const el = document.getElementById(id);
      if (el && el.getBoundingClientRect().top <= offset) {
        current = id as SectionId;
      }
    }
    setActive(current);
    ticking.current = false;
  }, []);

  useEffect(() => {
    const onScroll = () => {
      if (!ticking.current) {
        ticking.current = true;
        requestAnimationFrame(updateActive);
      }
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    const t = setTimeout(() => updateActive(), 0); // set initial state
    return () => {
      window.removeEventListener("scroll", onScroll);
      clearTimeout(t);
    };
  }, [updateActive]);

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <div className="border-b border-card-border sticky top-0 bg-background/95 backdrop-blur-sm z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-3 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 sm:gap-3 min-w-0">
            <Link href="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity">
              <div className="w-7 h-7 rounded-lg bg-accent flex items-center justify-center shrink-0">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#09090b" strokeWidth="2.5"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
              </div>
              <span className="font-bold text-sm shrink-0">TrustMesh</span>
            </Link>
            <span className="text-xs text-foreground/40 font-mono hidden sm:inline">docs</span>
          </div>
          <div className="flex items-center gap-1.5 sm:gap-2 shrink-0">
            <a href="http://localhost:8100" target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-foreground/50 hover:text-foreground transition-colors px-2 sm:px-3 py-1.5 rounded-lg hover:bg-card-hover">
              Registry
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="opacity-60"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
            </a>
            <Link href="/about" className="text-xs text-foreground/50 hover:text-foreground transition-colors px-2 sm:px-3 py-1.5 rounded-lg hover:bg-card-hover hidden sm:inline-flex">Why TrustMesh?</Link>
            <Link href="/" className="text-xs bg-accent text-accent-fg px-3 py-1.5 rounded-lg font-medium hover:bg-accent-hover transition-colors">Demo</Link>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto flex">
        {/* Sidebar nav */}
        <nav className="w-52 shrink-0 sticky top-[53px] h-[calc(100vh-53px)] overflow-y-auto border-r border-card-border py-6 px-4 hidden md:block">
          {SECTIONS.map((s, i) => {
            const showGroup = i === 0 || s.group !== SECTIONS[i - 1].group;
            return (
              <div key={s.id}>
                {showGroup && (
                  <p className="text-[9px] font-bold uppercase tracking-widest text-foreground/30 mt-4 mb-1.5 px-3 first:mt-0">
                    {s.group}
                  </p>
                )}
                <a
                  href={`#${s.id}`}
                  className={cn(
                    "block px-3 py-1.5 rounded-lg text-xs font-medium transition-colors mb-0.5",
                    active === s.id ? "bg-accent/10 text-accent" : "text-foreground/50 hover:text-foreground hover:bg-card-hover"
                  )}
                >
                  {s.label}
                </a>
              </div>
            );
          })}
        </nav>

        {/* Content */}
        <main className="flex-1 min-w-0 px-8 py-8 max-w-4xl">
          {/* What is a Pod? */}
          <div id="what">
            <div className="mb-2">
              <span className="text-[10px] font-bold uppercase tracking-widest text-accent">Getting Started</span>
            </div>
            <h1 className="text-3xl font-bold mb-3">TrustMesh Pods</h1>

            <div className="rounded-2xl border border-accent/20 bg-accent/5 p-6 mb-6">
              <p className="text-base text-foreground leading-relaxed mb-3">
                <strong>Think of TrustMesh like a smart address book that talks.</strong>
              </p>
              <p className="text-sm text-foreground/70 leading-relaxed mb-3">
                You store your knowledge &mdash; health info, work notes, family details, whatever matters to you &mdash;
                in your own encrypted space called a <strong className="text-foreground">vault</strong>. Then your personal AI agent
                answers questions from the people you choose. Your doctor asks about your medications? Your agent answers.
                A stranger asks the same thing? Silence.
              </p>
              <p className="text-sm text-foreground/70 leading-relaxed mb-3">
                You decide who&apos;s trusted by creating <strong className="text-foreground">connections</strong> (one-on-one relationships)
                and <strong className="text-foreground">pools</strong> (groups, like &ldquo;My Family&rdquo; or &ldquo;My Care Team&rdquo;).
                Each connection can have a label &mdash; spouse, doctor, colleague &mdash; and each pool can limit what type
                of data gets shared.
              </p>
              <p className="text-sm text-foreground/70 leading-relaxed">
                Everything runs on your <strong className="text-foreground">pod</strong> &mdash; a lightweight personal server
                that works completely on its own. No cloud accounts, no central authority.
                Connect your pod to other pods when you want to share. Disconnect when you don&apos;t.
              </p>
            </div>

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
                { label: "Agent", value: "Gemini 3.1 Pro", sub: "Trust-aware AI" },
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
uv run uvicorn src.main:app --reload --port 9000`}</Code>

          <P>Your pod is now running at <InlineCode>http://localhost:9000</InlineCode>. Check it:</P>
          <Code lang="bash">{`# Pod identity
curl http://localhost:9000/api/pod

# A2A agent card (how other pods find you)
curl http://localhost:9000/.well-known/agent-card.json

# Health check
curl http://localhost:9000/health`}</Code>

          <Callout type="tip">
            <strong>Dev mode:</strong> Use <InlineCode>./dev.sh start</InlineCode> from the repo root to start both backend and frontend automatically.
          </Callout>

          <H3>Environment variables</H3>
          <Table
            headers={["Variable", "Default", "Purpose"]}
            rows={[
              ["TRUSTMESH_POD_NAME", "TrustMesh Pod", "Display name for your pod"],
              ["TRUSTMESH_POD_URL", "http://localhost:9000", "Public URL for federation"],
              ["TRUSTMESH_DB", "./trustmesh.db", "SQLite database path (each pod gets its own)"],
              ["GOOGLE_API_KEY", "(primary)", "Gemini 3.1 Pro agent responses + Gemini Live voice"],
              ["ANTHROPIC_API_KEY", "(fallback)", "Claude 4.6 fallback if no Google key"],
              ["REDPILL_API_KEY", "(optional)", "RedPill TEE for sensitive medical/financial data"],
              ["VOYAGE_API_KEY", "(optional)", "Voyage AI embeddings (falls back to local)"],
              ["TRUSTMESH_POOL_SYNC_SECRET", "(generated)", "Shared secret for pool-sync federation auth"],
              ["TRUSTMESH_REGISTRY_URL", "http://localhost:8100", "Public agent registry URL"],
              ["TAVILY_API_KEY", "(optional)", "Web search tool for agents"],
            ]}
          />

          {/* CLI & MCP */}
          <H2 id="cli">CLI &amp; MCP Integration</H2>
          <P>
            TrustMesh includes a command-line interface for power users and an MCP server
            for AI tool integration (Claude Desktop, Cursor, etc.).
          </P>

          <H3>Install</H3>
          <Code lang="bash">{`cd trustmesh-core
uv sync   # installs the 'trustmesh' CLI command`}</Code>

          <H3>Authentication</H3>
          <Code lang="bash">{`# Log in to a pod (saves session to ~/.trustmesh/session)
trustmesh login --pod http://localhost:9000

# Check connection status
trustmesh status

# Who am I?
trustmesh whoami

# Log out
trustmesh logout`}</Code>

          <H3>Vault commands</H3>
          <Code lang="bash">{`# Search your vault
trustmesh vault search "allergies"

# List all capsules (with sharing info)
trustmesh vault list

# Get a specific capsule
trustmesh vault get <capsule-id>

# Add a new capsule
trustmesh vault add --title "Meeting Notes" --category work

# Archive a capsule
trustmesh vault archive <capsule-id>`}</Code>

          <H3>Agent commands</H3>
          <Code lang="bash">{`# One-shot question
trustmesh agent ask "What medications does Peter take?"

# Interactive chat session
trustmesh agent chat`}</Code>

          <H3>Connections &amp; Networks</H3>
          <Code lang="bash">{`# List your connections (shows relationship type + labels)
trustmesh connections list

# Send a connection request
trustmesh connections request <username>

# Accept a pending request
trustmesh connections accept <request-id>

# List your networks/pools
trustmesh networks list

# See members of a network
trustmesh networks members <network-id>

# Create a new network
trustmesh networks create --name "Book Club"`}</Code>

          <H3>Pod federation</H3>
          <Code lang="bash">{`# Pod identity and status
trustmesh pod info

# List connected peers
trustmesh pod peers

# Connect to another pod
trustmesh pod connect http://localhost:9001

# Disconnect from a peer (cascades ghost cleanup)
trustmesh pod disconnect <peer-id>

# Discover agents across all peers
trustmesh pod discover

# Toggle public registry visibility
trustmesh pod golive`}</Code>

          <H3>Registry</H3>
          <Code lang="bash">{`# List all publicly registered agents
trustmesh registry list

# Search the registry
trustmesh registry search "doctor"`}</Code>

          <H3>MCP server</H3>
          <P>
            The MCP server lets AI assistants (Claude Desktop, Cursor, etc.) use your TrustMesh pod as a tool.
            It reads your session from <InlineCode>~/.trustmesh/session</InlineCode>, so log in first.
          </P>
          <Code lang="bash">{`# Start the MCP server (stdio transport)
trustmesh mcp serve`}</Code>

          <P>Add to your Claude Desktop config:</P>
          <Code lang="json">{`{
  "mcpServers": {
    "trustmesh": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/trustmesh-core", "trustmesh", "mcp", "serve"]
    }
  }
}`}</Code>

          <Callout type="tip">
            The CLI stores its session at <InlineCode>~/.trustmesh/session</InlineCode>.
            Both the CLI and MCP server share this session, so one login covers both.
          </Callout>

          {/* Trust Levels */}
          <H2 id="trust">Trust Levels</H2>
          <P>
            TrustMesh resolves trust between any two users into one of four levels. Each level controls what
            capsules are visible and how the agent responds.
          </P>

          <Table
            headers={["Level", "UI Label", "When", "Capsule Access"]}
            rows={[
              ["private", "Private", "You query your own agent", "All capsules (full vault access)"],
              ["network", "Shared", "Users share a pool (network)", "Open + internal capsules shared to that pool"],
              ["connected", "Connected", "Users are connected but share no pools", "Open capsules only (agent acknowledges relationship)"],
              ["public", "Open", "No connection or pool at all (strangers)", "Open capsules only (strict information boundaries)"],
            ]}
          />

          <H3>How trust is resolved</H3>
          <Code lang="text">{`resolve_trust_level(from_user, to_user):
  1. Same user?           → "private"
  2. Share any pool?      → "network" + list of shared pools
  3. Have a connection?   → "connected"
  4. Otherwise            → "public"`}</Code>

          <Callout type="info">
            Pool membership alone grants &ldquo;network&rdquo; trust &mdash; no direct connection required.
            But a direct connection without a shared pool gives &ldquo;connected&rdquo; trust, which is
            better than public (the agent can acknowledge the relationship) but doesn&apos;t unlock internal capsules.
          </Callout>

          <H3>Trust in the UI</H3>
          <P>
            Trust levels appear as colored badges throughout the app:
            <strong className="text-warning"> Open</strong> (orange) for public capsules,
            <strong className="text-accent"> Shared</strong> (purple) for network-scoped capsules,
            <strong className="text-blue-400"> Connected</strong> (blue) for connected-only access, and
            <strong className="text-danger"> Private</strong> (red) for private capsules.
          </P>

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
            <li>Others join via invite link or pool-sync</li>
            <li>Pool membership alone grants &ldquo;Shared&rdquo; trust &mdash; no connection needed</li>
            <li>Each pod retains full sovereignty &mdash; the pool doesn&apos;t control your pod</li>
            <li>Pool members see &ldquo;Open&rdquo; + &ldquo;Internal&rdquo; capsules shared to that pool</li>
          </ul>

          <H3>Category-scoped pools</H3>
          <P>
            Pools can be scoped to specific data categories. A &ldquo;Health Pool&rdquo; with{" "}
            <InlineCode>shared_categories: [&quot;health&quot;]</InlineCode> only exposes health-related capsules
            to members, even if other internal capsules are shared to the same pool. Standard pools have no
            category filter and show everything.
          </P>

          <Table
            headers={["Pool Type", "Category Filter", "Use Case"]}
            rows={[
              ["standard", "None (all internal capsules)", "Family, general teams"],
              ["category_scoped", "Only matching categories", "Health circles, work projects"],
              ["public_registry", "None", "Public discovery pools"],
            ]}
          />

          {/* Connections */}
          <H2 id="connections">Connections &amp; Relationships</H2>
          <P>
            Connections are direct trust links between two people. Each connection can have a{" "}
            <strong className="text-foreground">relationship type</strong> and personal{" "}
            <strong className="text-foreground">labels</strong> that each side sets independently.
          </P>

          <Table
            headers={["Relationship Type", "Example Labels"]}
            rows={[
              ["family", "spouse, parent, child, son, daughter, sibling, grandparent"],
              ["friend", "close friend, childhood friend"],
              ["work", "boss, manager, colleague, mentor, direct report"],
              ["healthcare", "doctor, nurse, therapist, caregiver"],
              ["neighbor", "next door"],
              ["emergency", "ICE contact, medical proxy"],
              ["other", "(freeform)"],
            ]}
          />

          <P>
            Labels are <strong className="text-foreground">perspective-based</strong>: Peter labels Molly as &ldquo;wife&rdquo;
            while Molly labels Peter as &ldquo;husband&rdquo;. The API resolves <InlineCode>my_label</InlineCode> and{" "}
            <InlineCode>peer_label</InlineCode> based on which user is viewing. Labels can be updated after the
            connection is created via <InlineCode>PATCH /api/connections/&#123;id&#125;/label</InlineCode>.
          </P>

          <Callout type="tip">
            Connection requests show the sender&apos;s relationship type and label. The receiver can add their own
            label when accepting. Both sides also see mutual connections and shared networks to help decide.
          </Callout>

          {/* Confidential AI */}
          <H2 id="confidential">Confidential AI</H2>
          <P>
            When you ask your agent a question, it needs an AI model to reason about the answer.
            But here&apos;s the problem: if your data leaves your pod and goes to a cloud AI service,
            that service can see your data. They could log it, use it for training, or get hacked.
          </P>
          <P>
            <strong className="text-foreground">Trusted Execution Environments (TEEs)</strong> solve this.
            A TEE is a locked room inside a computer chip. Your data goes in, the AI processes it, the answer comes out &mdash;
            but nobody can peek inside. Not the cloud provider, not the AI company, not even the server administrator.
            The hardware itself enforces the privacy, and you can <strong className="text-foreground">verify</strong> it
            cryptographically.
          </P>

          <Callout type="tip">
            <strong>Why this matters:</strong> Your health records, financial data, and private conversations
            never become training data. They&apos;re processed inside sealed hardware and discarded.
            No logs, no leaks, no &ldquo;we updated our privacy policy.&rdquo;
          </Callout>

          <H3>How TrustMesh uses TEEs</H3>
          <P>
            Your pod automatically routes sensitive data through a TEE when it needs AI reasoning.
            Health capsules, financial records, anything tagged as private &mdash; the model runs inside
            a hardware enclave. You don&apos;t have to think about it.
          </P>

          <Code lang="text">{`Standard query (e.g. "what's my schedule?"):
  Pod → Google API → Gemini 3.1 Pro → response
  Best reasoning and tool calling

Sensitive query (e.g. "what are my medications?"):
  Pod → RedPill TEE enclave → Kimi K2.5 → response
  Hardware-attested privacy, nobody sees your plaintext

Offline / local query:
  Pod → Ollama (local model) → response
  Nothing leaves your device, ever`}</Code>

          <P>
            The experience degrades gracefully. If you don&apos;t have a cloud API key, the pod
            still works with TEE models or local models. If you have no internet at all, you can
            still read your vault and manage your data.
          </P>

          <Code lang="text">{`Gemini 3.1 Pro  →  RedPill TEE  →  Local model  →  Vault-only mode
  (best)           (very good)    (adequate)       (no AI, still works)`}</Code>

          <H3>TEE providers</H3>
          <P>
            Several services run AI models inside TEEs today. Your pod can connect to any of them:
          </P>

          <Table
            headers={["Provider", "What they do", "Hardware", "Models"]}
            rows={[
              ["Tinfoil", "Open-source confidential AI platform (YC X25)", "NVIDIA H100/Blackwell + AMD SEV-SNP", "DeepSeek R1 70B, Llama 3.3 70B, Mistral 3.1 24B"],
              ["RedPill", "TEE proxy to 200+ models, zero data retention", "NVIDIA GPU TEE + Intel TDX", "GPT, Claude, Gemini, open-source models via TEE proxy"],
              ["Ollama", "Run models locally on your own machine", "Your CPU/GPU (no cloud)", "Llama 3, Mistral, Gemma, Phi, Qwen, 100+ models"],
            ]}
          />

          <P>
            <a href="https://tinfoil.sh/technology" target="_blank" rel="noopener noreferrer" className="text-accent hover:text-accent-hover transition-colors underline">Tinfoil</a> runs
            fully open-source enclaves on NVIDIA confidential computing GPUs. Everything is auditable and cryptographically verifiable &mdash;
            you can prove that the code running inside the enclave is exactly what they published.
          </P>
          <P>
            <a href="https://www.redpill.ai" target="_blank" rel="noopener noreferrer" className="text-accent hover:text-accent-hover transition-colors underline">RedPill</a> takes
            a different approach: they wrap existing models (including proprietary ones) in a TEE proxy,
            so your prompts and responses are encrypted end-to-end. The model provider never sees your data.
            TEE mode runs at 99% of native speed.
          </P>
          <P>
            <a href="https://ollama.com" target="_blank" rel="noopener noreferrer" className="text-accent hover:text-accent-hover transition-colors underline">Ollama</a> is
            the simplest option: run models directly on your laptop or server. Nothing ever leaves your device.
            No API keys, no internet required after downloading a model. Best for people who want complete control.
          </P>

          <H3>NVIDIA confidential computing</H3>
          <P>
            All of this is built on{" "}
            <a href="https://www.nvidia.com/en-us/data-center/solutions/confidential-computing/" target="_blank" rel="noopener noreferrer" className="text-accent hover:text-accent-hover transition-colors underline">
              NVIDIA&apos;s confidential computing platform
            </a>.
            Starting with the H100 GPU, NVIDIA added hardware-level TEEs that protect GPU execution, memory, and register states.
            The Blackwell architecture expanded this with nearly zero performance overhead. And in 2026, the Vera Rubin platform
            delivers rack-scale confidential computing across CPU, GPU, and NVLink domains.
          </P>
          <P>
            In plain terms: the biggest GPU maker in the world is making it possible to run AI
            on their chips without anyone &mdash; including the data center operator &mdash; being able to see what&apos;s being processed.
          </P>

          <H3>Running pods in TEEs</H3>
          <P>
            For maximum security, the entire pod can run inside a TEE &mdash; not just the AI model, but
            the vault, the trust engine, and the agent itself. This means your encrypted data is decrypted
            only inside sealed hardware. Even on a shared cloud server, your pod is a black box.
          </P>

          <Table
            headers={["What runs in TEE", "What it protects", "Who can see your data"]}
            rows={[
              ["Just the AI model", "Prompts and responses during inference", "Nobody during processing"],
              ["AI model + vault decryption", "Capsule content + AI reasoning", "Nobody, not even the server operator"],
              ["Entire pod", "Everything — identity, vault, trust rules, agent", "Only you, through your encrypted session"],
            ]}
          />

          <Callout type="info">
            <strong>The bottom line:</strong> Your data is encrypted at rest in your vault (AES-256-GCM).
            When it needs to be processed by AI, it&apos;s decrypted inside sealed hardware that nobody can peek into.
            And if you don&apos;t trust any cloud at all, run everything locally with Ollama.
            TrustMesh gives you the choice.
          </Callout>

          {/* Connect Two Pods */}
          <H2 id="connect">Connect Two Pods</H2>
          <P>Federation starts with <strong className="text-foreground">peering</strong> &mdash; two pods that know about each other.</P>

          <H3>1. Start two pods on different ports</H3>
          <Code lang="bash">{`# Terminal 1: Johnson Family Pod
TRUSTMESH_POD_NAME="Johnson Family" \\
TRUSTMESH_POD_URL=http://localhost:9000 \\
TRUSTMESH_DB=./pod_a.db \\
uv run uvicorn src.main:app --port 9000

# Terminal 2: Hospital Pod
TRUSTMESH_POD_NAME="Riverside Hospital" \\
TRUSTMESH_POD_URL=http://localhost:9001 \\
TRUSTMESH_DB=./pod_b.db \\
uv run uvicorn src.main:app --port 8001`}</Code>

          <H3>2. Connect them</H3>
          <Code lang="bash">{`# Pod A connects to Pod B (bidirectional — Pod B learns about Pod A too)
curl -X POST http://localhost:9000/api/pod/peers \\
  -H "Content-Type: application/json" \\
  -d '{"url": "http://localhost:9001"}'

# Verify: Pod B now lists Pod A as a peer
curl http://localhost:9001/api/pod/peers`}</Code>

          <H3>3. Discover agents across federation</H3>
          <Code lang="bash">{`# From Pod A: see all agents (local + remote)
curl http://localhost:9000/api/pod/discover`}</Code>

          <H3>4. Cross-pod query</H3>
          <Code lang="bash">{`# Query a user on Pod B from Pod A
curl -X POST http://localhost:9001/api/pod/query \\
  -H "Content-Type: application/json" \\
  -d '{
    "from_did": "did:key:z6Mk...",
    "from_pod": "http://localhost:9000",
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

          {/* Architecture */}
          <H2 id="layers">The 5 Layers</H2>
          <P>TrustMesh federation has 5 layers, each independent and composable:</P>

          <Table
            headers={["Layer", "Name", "What It Does", "Status"]}
            rows={[
              ["1", "Pod", "One person = one pod. Standalone, works offline.", "Built"],
              ["2", "Peering", "Two pods directly connected. Bidirectional trust.", "Built"],
              ["3", "Pools", "Group of pods sharing trust. Category-scoped access.", "Built"],
              ["4", "Registry", "Optional public discoverability. Phone book for agents.", "Built"],
              ["5", "Open Federation", "A2A-compatible. Any agent can talk to your pod.", "Built"],
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
  "url": "http://localhost:9000/api/pod/a2a",
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
    "pod_url": "http://localhost:9000",
    "protocol": "trustmesh/0.1",
    "did": "did:key:z6Mk...",
    "public_key_b64": "..."
  }
}`}</Code>

          <P>
            The <InlineCode>trustmesh</InlineCode> extension contains TrustMesh-specific metadata. Standard A2A clients
            can ignore it and still discover the agent via the standard fields.
          </P>

          {/* Public Registry */}
          <H2 id="registry">Public Registry</H2>
          <P>
            The registry is a standalone service (port 8100) that acts as a phone book for agents across the network.
            Pods can optionally register their agents for public discovery.
          </P>

          <Table
            headers={["Method", "Endpoint", "Description"]}
            rows={[
              ["GET", "/api/health", "Registry health and agent count"],
              ["POST", "/api/register", "Register an agent (signed with ed25519 or unsigned)"],
              ["GET", "/api/agents", "List all registered agents"],
              ["GET", "/api/agents/{did}", "Look up a specific agent by DID"],
              ["GET", "/api/search?q=...", "Search agents by name, capability, or type"],
              ["DELETE", "/api/agents/{did}", "Deregister an agent"],
            ]}
          />

          <P>
            Registration can be <strong className="text-foreground">signed</strong> (ed25519 signature verified by the registry)
            or <strong className="text-foreground">unsigned</strong> (accepted as &ldquo;unverified&rdquo; for backward compatibility).
            Users can toggle discoverability with the &ldquo;Go Live&rdquo; toggle in their profile, which triggers
            automatic registration/deregistration.
          </P>

          <Callout type="info">
            The registry is optional. Pods work fine without it. It just makes discovery easier for people who
            want to be found.
          </Callout>

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
              ["POST", "/api/pod/peers", "Session / Secret", "Connect to a peer pod (bidirectional)"],
              ["DELETE", "/api/pod/peers/{id}", "Session / Secret", "Disconnect from a peer pod"],
              ["POST", "/api/pod/peers/{id}/ping", "Session / Secret", "Health check a specific peer"],
            ]}
          />

          <H3>Cross-Pod</H3>
          <Table
            headers={["Method", "Endpoint", "Auth", "Description"]}
            rows={[
              ["GET", "/api/pod/discover", "None", "Discover agents across all connected peers"],
              ["POST", "/api/pod/query", "None", "Receive incoming cross-pod gossip query"],
              ["POST", "/api/pod/a2a", "None", "A2A JSON-RPC endpoint (agent-to-agent messaging)"],
              ["POST", "/api/pod/pool-sync", "Secret", "Orchestrator-driven pool formation across pods"],
            ]}
          />

          <H3>Core API (unchanged)</H3>
          <Table
            headers={["Category", "Key Endpoints"]}
            rows={[
              ["Auth", "POST /api/auth/login, POST /api/auth/logout, GET /api/auth/me"],
              ["Capsules", "GET /api/users/{id}/capsules, POST /api/users/{id}/capsules"],
              ["Connections", "POST /api/connections/request, PATCH /api/connections/{id}/label"],
              ["Queries", "POST /api/query, POST /api/query/stream"],
              ["Networks", "POST /api/networks, GET /api/users/{id}/networks"],
              ["Registry", "GET /api/registry/agents, GET /api/registry/search"],
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
  1. IDENTIFY       Look up target user locally
  2. TRUST RESOLVE  Ghost user → "network" (if pool member)
                    Local connection → "connected"
                    Unknown → "public" (default)
  3. CITADEL IN     Scan incoming question for threats
  4. CAPSULE FILTER Trust-based: public→open only, connected→open,
                    network→open+internal in shared pools
  5. SEMANTIC SEARCH Match question against permitted capsules
  6. LLM GENERATE   Gemini responds from permitted data only
  7. CITADEL OUT    Trust-aware scan (soft-leak patterns at public trust)
  8. AUDIT LOG      Record: remote DID, source pod, trust level, decision
  9. RETURN         Send response back to Pod A`}</Code>

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
              ["Malicious remote query", "Citadel input scanning (prompt injection, jailbreak, tool manipulation)"],
              ["Data exfiltration", "Citadel output scanning with trust-aware soft-leak detection"],
              ["Information leaking", "6 soft-leak pattern categories (member referral, network structure, etc.)"],
              ["Impersonation / DID spoofing", "ed25519 DID verification + ghost pod URL cross-check"],
              ["Rogue peer pod", "Trust levels + federation auth (session or pool-sync secret)"],
              ["Ghost user abuse", "Per-pod ghost cap (100), per-network cap (20), stale ghost cleanup"],
              ["Flood / DoS", "Rate limiting per DID, scaling with trust level (5/hr public, 20/hr network)"],
              ["Audit evasion", "Immutable audit log with remote DID, source pod, trust level, and decision"],
            ]}
          />

          <H3>Trust escalation</H3>
          <P>Trust is earned progressively:</P>
          <Code lang="text">{`Unknown agent → "public" trust → sees only open capsules
    |
Peered pods → still "public" → needs user-level relationship
    |
User connection → "connected" trust → open capsules, agent acknowledges you
    |
Pool membership → "network" trust → sees internal capsules in shared pools
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
          <div className="mt-16 pt-8 border-t border-card-border text-center space-y-1">
            <p className="text-xs text-foreground/40">
              Built with love by <a href="https://github.com/masterfung" target="_blank" rel="noopener noreferrer" className="text-accent hover:text-accent-hover transition-colors">@masterfung</a>
            </p>
            <p className="text-xs text-foreground/40">
              TrustMesh v0.1 &middot; <Link href="/" className="text-accent hover:text-accent-hover transition-colors">Demo</Link> &middot; <Link href="/about" className="text-accent hover:text-accent-hover transition-colors">Why TrustMesh?</Link>
            </p>
          </div>
        </main>
      </div>
    </div>
  );
}
