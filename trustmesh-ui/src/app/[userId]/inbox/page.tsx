"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import {
  getInbox,
  getSent,
  getUnreadCount,
  markMessageRead,
  deleteMessage,
  type MessageItem,
} from "@/lib/api";

// ── Helpers ──────────────────────────────────────────────────────────────────

function timeAgo(dateStr: string): string {
  const now = new Date();
  const date = new Date(dateStr);
  const seconds = Math.floor((now.getTime() - date.getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return date.toLocaleDateString();
}

function expiryLabel(expiresAt: string): string {
  const now = Date.now();
  const exp = new Date(expiresAt).getTime();
  const ms = exp - now;
  if (ms <= 0) return "expired";
  const h = Math.floor(ms / 3_600_000);
  if (h < 1) return "<1h";
  if (h < 24) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
}

function isExpiringSoon(expiresAt: string): boolean {
  const ms = new Date(expiresAt).getTime() - Date.now();
  return ms > 0 && ms < 24 * 3_600_000;
}

// ── Trust badge ───────────────────────────────────────────────────────────────

function TrustBadge({ level }: { level: string }) {
  const colors: Record<string, string> = {
    network: "bg-sky-500/15 text-sky-400 border-sky-500/30",
    connected: "bg-accent/15 text-accent border-accent/30",
    private: "bg-violet-500/15 text-violet-400 border-violet-500/30",
  };
  const cls = colors[level] ?? "bg-muted/15 text-muted-foreground border-muted/30";
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium border ${cls}`}>
      {level}
    </span>
  );
}

// ── Message row ───────────────────────────────────────────────────────────────

function MessageRow({
  msg,
  isSent,
  userId,
  expanded,
  onExpand,
  onDelete,
}: {
  msg: MessageItem;
  isSent: boolean;
  userId: string;
  expanded: boolean;
  onExpand: () => void;
  onDelete: () => void;
}) {
  const name = isSent ? msg.recipient_id : msg.sender_display_name;

  return (
    <div
      className={`border-b border-card-border/50 transition-colors ${
        !isSent && !msg.is_read ? "bg-accent-glow/20" : "hover:bg-card-hover/50"
      }`}
    >
      <button
        className="w-full text-left px-4 py-3 flex items-start gap-3"
        onClick={onExpand}
      >
        {/* Unread dot */}
        <span
          className={`mt-1.5 w-2 h-2 rounded-full shrink-0 ${
            !isSent && !msg.is_read ? "bg-accent" : "bg-transparent"
          }`}
        />

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <span className={`text-sm truncate ${!isSent && !msg.is_read ? "font-semibold text-foreground" : "text-muted-foreground"}`}>
              {isSent ? `To: ${name}` : name}
            </span>
            <span className="text-[11px] text-muted-foreground shrink-0">{timeAgo(msg.created_at)}</span>
          </div>
          <p className={`text-sm mt-0.5 truncate ${!isSent && !msg.is_read ? "text-foreground" : "text-muted-foreground"}`}>
            {msg.subject}
          </p>
          {/* Badges */}
          <div className="flex items-center gap-1.5 mt-1.5">
            <TrustBadge level={msg.trust_level_at_send} />
            {msg.expires_at && (
              <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium border ${
                isExpiringSoon(msg.expires_at)
                  ? "bg-warning/15 text-warning border-warning/30"
                  : "bg-muted/10 text-muted-foreground border-muted/20"
              }`}>
                {expiryLabel(msg.expires_at)}
              </span>
            )}
            {msg.sender_pod_url && (
              <span className="px-1.5 py-0.5 rounded text-[10px] font-medium border bg-violet-500/10 text-violet-400 border-violet-500/20">
                cross-pod
              </span>
            )}
          </div>
        </div>
      </button>

      {/* Expanded body */}
      {expanded && (
        <div className="px-9 pb-3">
          <div className="bg-card rounded-xl p-3 border border-card-border/50">
            {msg.body ? (
              <p className="text-sm text-foreground whitespace-pre-wrap leading-relaxed">{msg.body}</p>
            ) : msg.rekey_needed ? (
              <p className="text-sm text-warning italic">Message encrypted — will be available after next login.</p>
            ) : (
              <p className="text-sm text-muted-foreground italic">Body unavailable.</p>
            )}
          </div>
          {!isSent && (
            <div className="flex items-center gap-2 mt-2">
              <button
                onClick={(e) => { e.stopPropagation(); onDelete(); }}
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs text-muted-foreground hover:text-danger hover:bg-danger-dim transition-colors"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
                  <path d="M10 11v6"/><path d="M14 11v6"/>
                </svg>
                Delete
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

type Tab = "inbox" | "unread" | "sent";

export default function InboxPage() {
  const { userId } = useParams<{ userId: string }>();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>("inbox");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const { data: inbox = [], isLoading: inboxLoading } = useQuery({
    queryKey: ["inbox", userId],
    queryFn: () => getInbox(userId),
    refetchInterval: 30_000,
  });

  const { data: sent = [], isLoading: sentLoading } = useQuery({
    queryKey: ["sent", userId],
    queryFn: () => getSent(userId),
    enabled: tab === "sent",
  });

  const { data: unreadCount = 0 } = useQuery({
    queryKey: ["inboxUnreadCount", userId],
    queryFn: () => getUnreadCount(userId),
    refetchInterval: 10_000,
  });

  const markReadMutation = useMutation({
    mutationFn: (messageId: string) => markMessageRead(messageId),
    onSuccess: (_data, messageId) => {
      queryClient.setQueryData(["inbox", userId], (old: MessageItem[] | undefined) =>
        old?.map((m) => (m.id === messageId ? { ...m, is_read: true } : m)) ?? []
      );
      queryClient.setQueryData(["inboxUnreadCount", userId], (old: number | undefined) =>
        Math.max(0, (old ?? 1) - 1)
      );
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (messageId: string) => deleteMessage(messageId),
    onSuccess: (_data, messageId) => {
      queryClient.setQueryData(["inbox", userId], (old: MessageItem[] | undefined) =>
        old?.filter((m) => m.id !== messageId) ?? []
      );
      if (expandedId === messageId) setExpandedId(null);
    },
  });

  const handleExpand = (msg: MessageItem, isSent: boolean) => {
    const newId = expandedId === msg.id ? null : msg.id;
    setExpandedId(newId);
    if (newId && !isSent && !msg.is_read) {
      markReadMutation.mutate(msg.id);
    }
  };

  const unread = inbox.filter((m) => !m.is_read);
  const messages = tab === "inbox" ? inbox : tab === "unread" ? unread : sent;
  const isSentTab = tab === "sent";
  const loading = tab === "sent" ? sentLoading : inboxLoading;

  return (
    <div className="max-w-3xl mx-auto space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-foreground">Inbox</h1>
          <p className="text-sm text-muted-foreground mt-0.5">Encrypted messages from your network</p>
        </div>
        {unreadCount > 0 && (
          <span className="flex items-center justify-center min-w-[28px] h-[28px] px-2 text-sm font-bold text-white bg-danger rounded-full">
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-card rounded-xl border border-card-border p-1 w-fit">
        {(["inbox", "unread", "sent"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all ${
              tab === t
                ? "bg-accent text-accent-fg shadow-sm"
                : "text-muted-foreground hover:text-foreground hover:bg-card-hover"
            }`}
          >
            {t === "unread" ? `Unread${unreadCount > 0 ? ` (${unreadCount})` : ""}` : t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {/* Message list */}
      <div className="bg-card rounded-2xl border border-card-border overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center py-16 text-muted-foreground text-sm animate-pulse">
            Loading messages...
          </div>
        ) : messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 px-4 gap-3">
            <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-muted-foreground">
              <polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/>
              <path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>
            </svg>
            <p className="text-sm text-muted-foreground">
              {tab === "unread" ? "No unread messages" : tab === "sent" ? "No sent messages" : "Your inbox is empty"}
            </p>
            {tab === "inbox" && (
              <p className="text-xs text-muted-foreground/70 text-center max-w-xs">
                Ask your agent to send a message: "Message Dr. Lee about my appointment"
              </p>
            )}
          </div>
        ) : (
          messages.map((msg) => (
            <MessageRow
              key={msg.id}
              msg={msg}
              isSent={isSentTab}
              userId={userId}
              expanded={expandedId === msg.id}
              onExpand={() => handleExpand(msg, isSentTab)}
              onDelete={() => deleteMutation.mutate(msg.id)}
            />
          ))
        )}
      </div>
    </div>
  );
}
