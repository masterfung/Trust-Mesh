"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type User, type QueryResult } from "@/lib/api";
import { useParams } from "next/navigation";
import { TrustBadge, DecisionBadge } from "@/components/TrustBadge";

export default function ChatPage() {
  const { userId } = useParams<{ userId: string }>();
  const queryClient = useQueryClient();
  const [targetId, setTargetId] = useState("");
  const [question, setQuestion] = useState("");
  const [results, setResults] = useState<QueryResult[]>([]);

  const { data: users } = useQuery({
    queryKey: ["users"],
    queryFn: api.listUsers,
  });
  const { data: user } = useQuery({
    queryKey: ["user", userId],
    queryFn: () => api.getUser(userId),
  });
  const { data: history } = useQuery({
    queryKey: ["queries", userId],
    queryFn: () => api.listQueries(userId),
  });

  const otherUsers = users?.filter((u: User) => u.id !== userId) ?? [];

  const mutation = useMutation({
    mutationFn: () => api.query(userId, targetId, question),
    onSuccess: (result) => {
      setResults((prev) => [result, ...prev]);
      setQuestion("");
      queryClient.invalidateQueries({ queryKey: ["queries", userId] });
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!targetId || !question.trim()) return;
    mutation.mutate();
  };

  const targetUser = otherUsers.find((u: User) => u.id === targetId);

  return (
    <div className="max-w-3xl mx-auto">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold mb-1">Ask Another Agent</h1>
        <p className="text-muted-foreground text-sm">
          Query another person&apos;s AI agent. Your trust level determines what knowledge they share.
        </p>
      </div>

      {/* Query Form */}
      <form onSubmit={handleSubmit} className="bg-card border border-card-border rounded-2xl p-5 mb-8">
        {/* Target Selection */}
        <div className="mb-5">
          <label className="block text-sm font-medium text-muted-foreground mb-2">Whose agent do you want to ask?</label>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            {otherUsers.map((u: User) => (
              <button
                key={u.id}
                type="button"
                onClick={() => setTargetId(u.id)}
                className={`p-3 rounded-xl text-left transition-all ${
                  targetId === u.id
                    ? "bg-accent/10 border-2 border-accent shadow-sm"
                    : "bg-card-hover border-2 border-transparent hover:border-card-border"
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <div className={`w-7 h-7 rounded-lg flex items-center justify-center text-white font-bold text-xs ${
                    targetId === u.id ? "bg-accent" : "bg-muted"
                  }`}>
                    {u.display_name[0]}
                  </div>
                  <span className="font-medium text-sm truncate">{u.display_name}</span>
                </div>
                <span className="text-[11px] text-muted truncate block">@{u.username}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Question Input */}
        <div className="mb-4">
          <label className="block text-sm font-medium text-muted-foreground mb-2">Your question</label>
          <div className="relative">
            <input
              type="text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder={
                targetUser
                  ? `Ask ${targetUser.display_name}'s agent...`
                  : "Select a person above..."
              }
              className="w-full bg-background border border-card-border rounded-xl px-4 py-3 text-sm pr-24 placeholder:text-muted"
              disabled={!targetId}
            />
            <button
              type="submit"
              disabled={!targetId || !question.trim() || mutation.isPending}
              className="absolute right-1.5 top-1.5 px-4 py-2 bg-accent hover:bg-accent-hover text-white text-sm font-medium rounded-lg disabled:opacity-40 disabled:cursor-not-allowed transition-all"
            >
              {mutation.isPending ? (
                <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                </svg>
              ) : "Send"}
            </button>
          </div>
        </div>

        {/* Trust Context Hint */}
        {targetUser && (
          <p className="text-[11px] text-muted flex items-center gap-1.5">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>
            </svg>
            Your trust level with {targetUser.display_name} determines which capsules their agent can access.
          </p>
        )}
      </form>

      {/* Results */}
      {results.length > 0 && (
        <div className="mb-8">
          <h2 className="text-sm font-semibold text-muted-foreground mb-3">This Session</h2>
          <div className="space-y-3">
            {results.map((r) => (
              <QueryResultCard key={r.id} result={r} users={users ?? []} currentUserId={userId} />
            ))}
          </div>
        </div>
      )}

      {/* History */}
      {history && history.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-muted-foreground mb-3">Query History</h2>
          <div className="space-y-3">
            {history.map((r: QueryResult) => (
              <QueryResultCard key={r.id} result={r} users={users ?? []} currentUserId={userId} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function QueryResultCard({
  result,
  users,
  currentUserId,
}: {
  result: QueryResult;
  users: User[];
  currentUserId: string;
}) {
  const fromUser = users.find((u) => u.id === result.from_user_id);
  const toUser = users.find((u) => u.id === result.to_user_id);
  const isSent = result.from_user_id === currentUserId;

  return (
    <div className="bg-card border border-card-border rounded-2xl overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-card-border bg-card-hover/30">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="font-semibold text-foreground">
            {isSent ? "You" : fromUser?.display_name}
          </span>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>
          </svg>
          <span className="font-semibold text-foreground">
            {isSent ? toUser?.display_name : "your"}&apos;s agent
          </span>
        </div>
        <div className="flex items-center gap-2">
          <TrustBadge tier={result.trust_level} />
          <DecisionBadge decision={result.decision} />
        </div>
      </div>

      {/* Body */}
      <div className="px-5 py-4">
        <p className="text-sm font-medium mb-3">&ldquo;{result.question}&rdquo;</p>

        {result.response && (
          <div
            className={`text-sm p-4 rounded-xl leading-relaxed ${
              result.decision === "allowed"
                ? "bg-success-dim border border-success/15"
                : result.decision === "denied"
                  ? "bg-danger-dim border border-danger/15"
                  : "bg-warning-dim border border-warning/15"
            }`}
          >
            {result.response}
          </div>
        )}

        {/* Metadata */}
        <div className="flex items-center gap-4 mt-3 text-[11px] text-muted">
          {result.shared_networks.length > 0 && (
            <span className="flex items-center gap-1">
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="5" r="3"/><circle cx="5" cy="19" r="3"/><circle cx="19" cy="19" r="3"/>
                <line x1="12" y1="8" x2="5" y2="16"/><line x1="12" y1="8" x2="19" y2="16"/>
              </svg>
              {result.shared_networks.join(", ")}
            </span>
          )}
          <span>{result.latency_ms}ms</span>
          {result.citadel_input?.decision && (
            <span className={`flex items-center gap-1 ${result.citadel_input.decision === "BLOCK" ? "text-danger" : "text-success"}`}>
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
              </svg>
              Citadel: {result.citadel_input.decision}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
