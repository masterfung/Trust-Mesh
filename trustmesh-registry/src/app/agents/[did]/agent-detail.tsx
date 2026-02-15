"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EntityBadge } from "@/components/EntityBadge";
import {
  ArrowLeft,
  Copy,
  Check,
  ExternalLink,
  Fingerprint,
  Globe,
  Shield,
  ChevronDown,
  ChevronRight,
  CircleCheck,
  CircleX,
  Loader2,
} from "lucide-react";
import type { AgentRecord } from "@/lib/db";

function avatarColor(entityType: string): string {
  switch (entityType) {
    case "organization": return "bg-purple-500/20 text-purple-400 border-purple-500/30";
    case "government": return "bg-emerald-500/20 text-emerald-400 border-emerald-500/30";
    default: return "bg-blue-500/20 text-blue-400 border-blue-500/30";
  }
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      onClick={handleCopy}
      className="p-1 rounded hover:bg-white/10 transition-colors"
      title="Copy to clipboard"
    >
      {copied ? (
        <Check className="size-3.5 text-green-400" />
      ) : (
        <Copy className="size-3.5 text-muted-foreground" />
      )}
    </button>
  );
}

export function AgentDetailClient({ agent }: { agent: AgentRecord }) {
  const [podStatus, setPodStatus] = useState<"checking" | "online" | "offline">("checking");
  const [agentCard, setAgentCard] = useState<Record<string, unknown> | null>(null);
  const [showAgentCard, setShowAgentCard] = useState(false);

  useEffect(() => {
    // Check pod health
    fetch(`${agent.pod_url}/health`, { signal: AbortSignal.timeout(5000) })
      .then((r) => setPodStatus(r.ok ? "online" : "offline"))
      .catch(() => setPodStatus("offline"));

    // Fetch A2A agent card
    fetch(`${agent.pod_url}/.well-known/agent-card.json`, { signal: AbortSignal.timeout(5000) })
      .then((r) => r.json())
      .then(setAgentCard)
      .catch(() => null);
  }, [agent.pod_url]);

  const displayName = agent.display_name || agent.name;
  const initial = displayName.charAt(0).toUpperCase();

  return (
    <div className="min-h-screen">
      {/* Header */}
      <header className="border-b border-white/5 bg-white/[0.01]">
        <div className="mx-auto max-w-4xl px-6 py-4 flex items-center gap-3">
          <Shield className="size-6 text-yellow-400" />
          <h1 className="text-lg font-semibold">
            <span className="text-gradient">TrustMesh</span> Agent Registry
          </h1>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-6 py-8 space-y-6">
        {/* Back link */}
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="size-4" />
          Back to Registry
        </Link>

        {/* Profile Card */}
        <Card className="bg-white/[0.02]">
          <CardHeader>
            <div className="flex items-start gap-4">
              <div
                className={`flex size-16 shrink-0 items-center justify-center rounded-full border text-2xl font-bold ${avatarColor(agent.entity_type)}`}
              >
                {initial}
              </div>
              <div className="min-w-0 flex-1 space-y-2">
                <div className="flex items-center gap-3 flex-wrap">
                  <CardTitle className="text-2xl">{displayName}</CardTitle>
                  <EntityBadge entityType={agent.entity_type} />
                </div>
                {agent.username && (
                  <p className="text-muted-foreground">@{agent.username}</p>
                )}
                {agent.bio && (
                  <p className="text-sm text-muted-foreground">{agent.bio}</p>
                )}
              </div>
            </div>
          </CardHeader>
        </Card>

        {/* DID */}
        <Card className="bg-white/[0.02]">
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Fingerprint className="size-4 text-yellow-400" />
              Decentralized Identifier (DID)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2 rounded-lg bg-black/30 px-4 py-3 border border-white/5">
              <code className="text-sm font-mono break-all flex-1">{agent.did}</code>
              <CopyButton text={agent.did} />
            </div>
            <p className="text-xs text-muted-foreground mt-2">
              Self-certifying ed25519 key — only the key holder can register this identity
            </p>
          </CardContent>
        </Card>

        {/* Capabilities */}
        {agent.capabilities.length > 0 && (
          <Card className="bg-white/[0.02]">
            <CardHeader>
              <CardTitle className="text-base">Capabilities</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-2">
                {agent.capabilities.map((cap) => (
                  <Badge key={cap} variant="secondary" className="text-xs">
                    {cap}
                  </Badge>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Pod Info */}
        <Card className="bg-white/[0.02]">
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Globe className="size-4 text-yellow-400" />
              Pod Information
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Pod URL</span>
              <a
                href={agent.pod_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm flex items-center gap-1.5 text-yellow-400 hover:underline"
              >
                {agent.pod_url}
                <ExternalLink className="size-3" />
              </a>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Status</span>
              <span className="text-sm flex items-center gap-1.5">
                {podStatus === "checking" && (
                  <>
                    <Loader2 className="size-3.5 animate-spin text-muted-foreground" />
                    Checking...
                  </>
                )}
                {podStatus === "online" && (
                  <>
                    <CircleCheck className="size-3.5 text-green-400" />
                    <span className="text-green-400">Online</span>
                  </>
                )}
                {podStatus === "offline" && (
                  <>
                    <CircleX className="size-3.5 text-red-400" />
                    <span className="text-red-400">Offline</span>
                  </>
                )}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Protocol</span>
              <span className="text-sm">trustmesh/0.1</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Registered</span>
              <span className="text-sm">
                {new Date(agent.registered_at).toLocaleDateString()}
              </span>
            </div>
          </CardContent>
        </Card>

        {/* A2A Agent Card (collapsible) */}
        <Card className="bg-white/[0.02]">
          <CardHeader>
            <button
              onClick={() => setShowAgentCard(!showAgentCard)}
              className="flex items-center gap-2 text-base font-semibold w-full text-left"
            >
              {showAgentCard ? (
                <ChevronDown className="size-4" />
              ) : (
                <ChevronRight className="size-4" />
              )}
              A2A Agent Card
              {agentCard ? (
                <Badge variant="secondary" className="text-[10px] ml-2">loaded</Badge>
              ) : (
                <Badge variant="outline" className="text-[10px] ml-2 text-muted-foreground">
                  {podStatus === "offline" ? "unavailable" : "loading"}
                </Badge>
              )}
            </button>
          </CardHeader>
          {showAgentCard && (
            <CardContent>
              {agentCard ? (
                <pre className="text-xs font-mono bg-black/30 rounded-lg p-4 overflow-auto max-h-96 border border-white/5">
                  {JSON.stringify(agentCard, null, 2)}
                </pre>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {podStatus === "offline"
                    ? "Pod is offline — agent card unavailable"
                    : "Loading agent card..."}
                </p>
              )}
            </CardContent>
          )}
        </Card>
      </main>
    </div>
  );
}
