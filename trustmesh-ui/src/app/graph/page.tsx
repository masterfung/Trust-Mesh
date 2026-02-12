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
        <div>
          <h1 className="text-xl font-bold text-accent">Trust Graph</h1>
          <p className="text-xs text-muted">Connections and networks visualized</p>
        </div>
        <Link
          href="/"
          className="px-3 py-1.5 text-xs bg-card border border-card-border rounded-lg hover:border-accent transition-colors"
        >
          Back to Home
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
