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
    <div className="max-w-3xl">
      <h1 className="text-2xl font-bold mb-1">Ask Another Agent</h1>
      <p className="text-muted text-sm mb-6">
        Query another person&apos;s AI agent. Your trust level determines what knowledge they share.
      </p>

      {/* Query Form */}
      <form onSubmit={handleSubmit} className="bg-card border border-card-border rounded-lg p-4 mb-6">
        <div className="mb-4">
          <label className="block text-xs text-muted mb-1.5">Ask whose agent?</label>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            {otherUsers.map((u: User) => (
              <button
                key={u.id}
                type="button"
                onClick={() => setTargetId(u.id)}
                className={`p-2 rounded-lg text-left text-sm border transition-colors ${
                  targetId === u.id
                    ? "border-accent bg-accent/10 text-accent"
                    : "border-card-border hover:border-accent/50"
                }`}
              >
                <span className="font-medium">{u.display_name}</span>
                <span className="block text-xs text-muted truncate">@{u.username}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="mb-3">
          <label className="block text-xs text-muted mb-1.5">Your question</label>
          <input
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder={
              targetUser
                ? `Ask ${targetUser.display_name}'s agent...`
                : "Select a person above..."
            }
            className="w-full bg-background border border-card-border rounded-lg px-3 py-2 text-sm focus:border-accent focus:outline-none"
            disabled={!targetId}
          />
        </div>

        <button
          type="submit"
          disabled={!targetId || !question.trim() || mutation.isPending}
          className="w-full bg-accent text-black font-medium py-2 rounded-lg text-sm hover:bg-accent-dim disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {mutation.isPending ? "Querying agent..." : "Send Query"}
        </button>
      </form>

      {/* Results */}
      {results.length > 0 && (
        <div className="space-y-4 mb-8">
          <h2 className="text-sm font-semibold text-muted">This Session</h2>
          {results.map((r) => (
            <QueryResultCard key={r.id} result={r} users={users ?? []} currentUserId={userId} />
          ))}
        </div>
      )}

      {/* History */}
      {history && history.length > 0 && (
        <div className="space-y-4">
          <h2 className="text-sm font-semibold text-muted">Query History</h2>
          {history.map((r: QueryResult) => (
            <QueryResultCard key={r.id} result={r} users={users ?? []} currentUserId={userId} />
          ))}
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
    <div className="bg-card border border-card-border rounded-lg p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 text-xs text-muted">
          <span className="font-medium text-foreground">
            {isSent ? "You" : fromUser?.display_name}
          </span>
          <span>asked</span>
          <span className="font-medium text-foreground">
            {isSent ? toUser?.display_name : "your"} agent
          </span>
        </div>
        <div className="flex items-center gap-2">
          <TrustBadge tier={result.trust_level} />
          <DecisionBadge decision={result.decision} />
        </div>
      </div>

      <p className="text-sm font-medium mb-2">&ldquo;{result.question}&rdquo;</p>

      {result.response && (
        <div
          className={`text-sm p-3 rounded-lg ${
            result.decision === "allowed"
              ? "bg-success/5 border border-success/20"
              : result.decision === "denied"
                ? "bg-danger/5 border border-danger/20"
                : "bg-warning/5 border border-warning/20"
          }`}
        >
          {result.response}
        </div>
      )}

      <div className="flex items-center gap-4 mt-3 text-xs text-muted">
        {result.shared_networks.length > 0 && (
          <span>Networks: {result.shared_networks.join(", ")}</span>
        )}
        <span>{result.latency_ms}ms</span>
        {result.citadel_input?.decision && (
          <span className={result.citadel_input.decision === "BLOCK" ? "text-danger" : "text-success"}>
            Citadel: {result.citadel_input.decision}
          </span>
        )}
      </div>
    </div>
  );
}
