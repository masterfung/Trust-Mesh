"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type User } from "@/lib/api";
import Link from "next/link";

const USER_COLORS: Record<string, string> = {
  peter: "from-blue-600 to-blue-400",
  molly: "from-purple-600 to-purple-400",
  jane: "from-pink-600 to-pink-400",
  bill: "from-green-600 to-green-400",
  kyle: "from-orange-600 to-orange-400",
};

export default function Home() {
  const { data: users, isLoading } = useQuery({
    queryKey: ["users"],
    queryFn: api.listUsers,
  });

  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-8">
      <div className="text-center mb-12">
        <h1 className="text-5xl font-bold text-accent mb-3">TrustMesh</h1>
        <p className="text-lg text-muted max-w-xl mx-auto">
          Trust-aware knowledge sharing for AI agents. Each person has an AI agent
          that holds their knowledge and shares it appropriately based on trust relationships.
        </p>
      </div>

      <div className="mb-6">
        <p className="text-muted text-sm text-center">Select a person to view their perspective:</p>
      </div>

      {isLoading ? (
        <div className="text-muted animate-pulse">Loading users...</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-4 max-w-5xl">
          {users?.map((user: User) => (
            <Link
              key={user.id}
              href={`/${user.id}`}
              className="group block p-5 rounded-xl bg-card border border-card-border hover:border-accent transition-all hover:scale-105"
            >
              <div
                className={`w-14 h-14 rounded-full bg-gradient-to-br ${USER_COLORS[user.username] || "from-gray-600 to-gray-400"} flex items-center justify-center text-white font-bold text-xl mb-3 group-hover:shadow-lg group-hover:shadow-accent/20 transition-shadow`}
              >
                {user.display_name[0]}
              </div>
              <h2 className="text-foreground font-semibold text-sm">{user.display_name}</h2>
              <p className="text-xs text-muted mt-1 line-clamp-2">{user.bio}</p>
            </Link>
          ))}
        </div>
      )}

      <div className="mt-12 flex gap-4">
        <Link
          href="/graph"
          className="px-4 py-2 rounded-lg bg-accent/10 text-accent text-sm hover:bg-accent/20 transition-colors"
        >
          View Trust Graph
        </Link>
      </div>

      <footer className="mt-16 text-xs text-muted text-center">
        <p>Built with Opus 4.6 for the Claude Code Hackathon</p>
        <p className="mt-1">Encryption: AES-256-GCM | Security: Citadel | AI: Claude Opus 4.6</p>
      </footer>
    </div>
  );
}
