"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { TrustGraph } from "@/components/TrustGraph";
import Link from "next/link";

export default function GraphPage() {
  const { data: graph, isLoading } = useQuery({
    queryKey: ["graph"],
    queryFn: api.getGraph,
  });

  return (
    <div className="min-h-screen bg-background">
      <div className="flex items-center justify-between p-4 border-b border-card-border">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-accent to-purple-500 flex items-center justify-center">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
            </svg>
          </div>
          <div>
            <h1 className="text-base font-bold">Trust Graph</h1>
            <p className="text-[11px] text-muted">Connections and networks visualized</p>
          </div>
        </div>
        <Link
          href="/"
          className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-card border border-card-border rounded-xl hover:border-accent/30 hover:bg-card-hover transition-all text-muted-foreground hover:text-foreground"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/>
          </svg>
          Back
        </Link>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center h-96">
          <div className="text-muted animate-pulse">Loading graph...</div>
        </div>
      ) : graph ? (
        <TrustGraph data={graph} />
      ) : (
        <div className="flex items-center justify-center h-96">
          <div className="text-danger">Failed to load graph data</div>
        </div>
      )}
    </div>
  );
}
