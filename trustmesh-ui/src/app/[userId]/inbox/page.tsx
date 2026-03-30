"use client";

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useParams, useSearchParams } from "next/navigation";
import {
  getInbox,
  getSent,
  getUnreadCount,
  markMessageRead,
  deleteMessage,
  api,
  type MessageItem,
  type Notification,
  type Capsule,
} from "@/lib/api";
import { TrustBadge } from "@/components/TrustBadge";
import { formatRelativeTime } from "@/lib/utils";
import { timeAgo } from "@/lib/utils";

// ── Helpers ──────────────────────────────────────────────────────────────────

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

// ── Message row ───────────────────────────────────────────────────────────────

function MessageRow({
  msg,
  isSent,
  expanded,
  onExpand,
  onDelete,
}: {
  msg: MessageItem;
  isSent: boolean;
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
            <span className="text-[11px] text-muted-foreground shrink-0">{formatRelativeTime(null, msg.created_at)}</span>
          </div>
          <p className={`text-sm mt-0.5 truncate ${!isSent && !msg.is_read ? "text-foreground" : "text-muted-foreground"}`}>
            {msg.subject}
          </p>
          {/* Badges */}
          <div className="flex items-center gap-1.5 mt-1.5">
            <TrustBadge tier={msg.trust_level_at_send} />
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

// ── Data Request card — inline vault reply ────────────────────────────────────

function DataRequestCard({
  notif,
  userId,
  onDone,
}: {
  notif: Notification;
  userId: string;
  onDone: () => void;
}) {
  const [reply, setReply] = useState("");
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState(false);

  const handleSave = async () => {
    if (!reply.trim()) return;
    setSaving(true);
    try {
      // Save the reply as a capsule to the user's vault
      await api.createCapsule(userId, {
        title: `Data shared with ${notif.title.replace("is asking for your help", "").trim()}`,
        content: reply,
        capsule_type: "note",
        tier: "internal",
        category: "general",
      });
      setDone(true);
      onDone();
    } catch (e) {
      console.error("Failed to save reply:", e);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="border border-amber-500/20 rounded-2xl overflow-hidden bg-amber-500/5 mb-4">
      <div className="flex items-start gap-3 p-4">
        <span className="text-xl shrink-0">📬</span>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-foreground">{notif.title}</p>
          <p className="text-xs text-muted-foreground mt-0.5">They asked:</p>
          <p className="text-sm text-amber-300 mt-1 font-medium italic">"{notif.body}"</p>
        </div>
      </div>

      {done ? (
        <div className="px-4 pb-4 flex items-center gap-2 text-sm text-emerald-400">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
          Saved to your vault — the requester will be notified automatically.
        </div>
      ) : (
        <div className="px-4 pb-4 space-y-2">
          <p className="text-xs text-muted-foreground">
            Reply below and your agent will save it to your vault and notify them automatically:
          </p>
          <textarea
            value={reply}
            onChange={(e) => setReply(e.target.value)}
            placeholder="Type your answer here…"
            rows={3}
            className="w-full px-3 py-2 text-sm bg-background border border-card-border rounded-xl focus:outline-none focus:border-accent resize-none"
          />
          <button
            onClick={handleSave}
            disabled={!reply.trim() || saving}
            className="px-4 py-2 text-xs font-semibold rounded-xl bg-accent hover:bg-accent-hover text-accent-fg transition-all disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save to Vault & Notify"}
          </button>
        </div>
      )}
    </div>
  );
}

// ── Query notification row ─────────────────────────────────────────────────────

function QueryRow({
  notif,
  userId,
  expanded,
  onExpand,
  onMarkRead,
  staleCapsuleCount,
}: {
  notif: Notification;
  userId: string;
  expanded: boolean;
  onExpand: () => void;
  onMarkRead: () => void;
  staleCapsuleCount?: number;
}) {
  const typeLabel: Record<string, string> = {
    query_received: "Query received",
    capsule_updated: "Shared data updated",
    query_response: "Query response",
    connection_request: "Connection request",
    connection_accepted: "Connection accepted",
    network_invite: "Network invite",
    network_joined: "Network joined",
    task_complete: "Task complete",
    emergency_access: "Emergency access",
  };

  const handleClick = () => {
    if (!notif.is_read) onMarkRead();
    onExpand();
  };

  return (
    <div className={`border-b border-card-border/50 transition-colors ${!notif.is_read ? "bg-accent-glow/20" : "hover:bg-card-hover/50"}`}>
      <button className="w-full text-left px-4 py-3 flex items-start gap-3" onClick={handleClick}>
        {/* Unread dot */}
        <span className={`mt-1.5 w-2 h-2 rounded-full shrink-0 ${!notif.is_read ? "bg-accent" : "bg-transparent"}`} />

        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <span className={`text-sm ${!notif.is_read ? "font-semibold text-foreground" : "text-muted-foreground"}`}>
              {notif.title}
            </span>
            <span className="text-[11px] text-muted-foreground shrink-0">{timeAgo(notif.created_at)}</span>
          </div>
          <p className={`text-sm mt-0.5 ${expanded ? "" : "line-clamp-2"} leading-relaxed ${!notif.is_read ? "text-foreground/80" : "text-muted-foreground"}`}>
            {notif.body}
          </p>
          <span className="inline-block mt-1.5 px-1.5 py-0.5 rounded text-[10px] font-medium border bg-violet-500/10 text-violet-400 border-violet-500/20">
            {typeLabel[notif.notification_type] ?? notif.notification_type}
          </span>
        </div>
      </button>

      {expanded && (
        <div className="px-9 pb-3">
          <div className="bg-card rounded-xl p-3 border border-card-border/50">
            <p className="text-sm text-foreground whitespace-pre-wrap leading-relaxed">{notif.body}</p>
          </div>
          {notif.notification_type === "capsule_updated" && (
            <div className="mt-2 space-y-2">
              {staleCapsuleCount != null && staleCapsuleCount > 0 && (
                <a
                  href={`/${userId}/vault`}
                  className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs bg-orange-500/10 border border-orange-500/20 text-orange-400 hover:bg-orange-500/15 transition-colors"
                >
                  <span>&#x26a0;</span>
                  <span>{staleCapsuleCount} capsule{staleCapsuleCount !== 1 ? "s" : ""} may be stale from this update</span>
                  <span className="ml-auto text-orange-400/60">Review in vault &rarr;</span>
                </a>
              )}
              <a
                href={`/${userId}/networks`}
                className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium text-muted-foreground hover:text-amber-400 hover:bg-amber-500/10 transition-colors border border-transparent hover:border-amber-500/20"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
                  <path d="M18.63 13A17.89 17.89 0 0 1 18 8"/>
                  <path d="M6.26 6.26A5.86 5.86 0 0 0 6 8c0 7-3 9-3 9h14"/>
                  <path d="M18 8a6 6 0 0 0-9.33-5"/>
                  <line x1="1" y1="1" x2="23" y2="23"/>
                </svg>
                Mute this network
              </a>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

type Tab = "inbox" | "unread" | "queries" | "sent";

export default function InboxPage() {
  const { userId } = useParams<{ userId: string }>();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();

  const initialTab = (searchParams.get("tab") as Tab | null) ?? "inbox";
  const [tab, setTab] = useState<Tab>(initialTab);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Reset expanded item when switching tabs
  useEffect(() => { setExpandedId(null); }, [tab]);

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

  const { data: allNotifications = [], isLoading: notifLoading } = useQuery({
    queryKey: ["notifications", userId],
    queryFn: () => api.listNotifications(userId),
    // Always fetch — data requests need to show on inbox tab too
    refetchInterval: 30_000,
  });

  const { data: capsules } = useQuery({
    queryKey: ["capsules", userId],
    queryFn: () => api.listCapsules(userId),
    enabled: tab === "queries",
  });
  const staleCapsuleCount = capsules?.filter((c: Capsule) => c.stale_since).length ?? 0;

  // Data requests bubble up to the top of the inbox tab
  const dataRequests = allNotifications.filter((n) => n.notification_type === "data_request" && !n.is_read);

  // All non-message notification types worth showing in the queries tab
  const queryNotifications = allNotifications.filter((n) =>
    ["query_received", "query_response", "connection_request", "connection_accepted",
     "network_invite", "network_joined", "task_complete", "emergency_access",
     "capsule_updated"].includes(n.notification_type)
  );
  const unreadQueryCount = allNotifications.filter((n) => !n.is_read).length;

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

  const markNotifReadMutation = useMutation({
    mutationFn: (notifId: string) => api.markNotificationRead(notifId),
    onSuccess: (_data, notifId) => {
      queryClient.setQueryData(["notifications", userId], (old: Notification[] | undefined) =>
        old?.map((n) => (n.id === notifId ? { ...n, is_read: true } : n)) ?? []
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
  const loading = tab === "sent" ? sentLoading : tab === "queries" ? notifLoading : inboxLoading;

  return (
    <div className="max-w-3xl mx-auto space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-foreground">Inbox</h1>
          <p className="text-sm text-muted-foreground mt-0.5">Encrypted messages from your network</p>
        </div>
        {unreadCount > 0 && tab !== "queries" && (
          <span className="flex items-center justify-center min-w-[28px] h-[28px] px-2 text-sm font-bold text-white bg-danger rounded-full">
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-card rounded-xl border border-card-border p-1 w-fit">
        {(["inbox", "unread", "queries", "sent"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all ${
              tab === t
                ? "bg-accent text-accent-fg shadow-sm"
                : "text-muted-foreground hover:text-foreground hover:bg-card-hover"
            }`}
          >
            {t === "unread"
              ? `Unread${unreadCount > 0 ? ` (${unreadCount})` : ""}`
              : t === "queries"
              ? `Queries${unreadQueryCount > 0 ? ` (${unreadQueryCount})` : ""}`
              : t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {/* Compose nudge — only for messages tabs */}
      {tab !== "queries" && (
        <div className="flex items-center gap-2.5 px-4 py-3 rounded-xl bg-accent/5 border border-accent/15">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-accent shrink-0">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
          <p className="text-xs text-muted-foreground">
            Ask your agent to send a message:{" "}
            <span className="font-medium text-accent/80">&quot;Send a message to [name] about...&quot;</span>
          </p>
        </div>
      )}

      {/* Data requests — shown at top of inbox tab */}
      {(tab === "inbox" || tab === "unread") && dataRequests.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs font-semibold text-amber-400 flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
            Data requests from connected agents
          </p>
          {dataRequests.map((notif) => (
            <DataRequestCard
              key={notif.id}
              notif={notif}
              userId={userId}
              onDone={() => queryClient.invalidateQueries({ queryKey: ["notifications", userId] })}
            />
          ))}
        </div>
      )}

      {/* Queries tab — shows agent query notifications */}
      {tab === "queries" ? (
        <div className="bg-card rounded-2xl border border-card-border overflow-hidden">
          {loading ? (
            <div className="flex items-center justify-center py-16 text-muted-foreground text-sm animate-pulse">
              Loading queries...
            </div>
          ) : queryNotifications.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 px-4 gap-3">
              <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-muted-foreground">
                <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
              </svg>
              <p className="text-sm text-muted-foreground">No agent queries yet</p>
              <p className="text-xs text-muted-foreground/70 text-center max-w-xs">
                When other agents query your agent for information, they&apos;ll appear here.
              </p>
            </div>
          ) : (
            queryNotifications.map((notif) => (
              <QueryRow
                key={notif.id}
                notif={notif}
                userId={userId}
                expanded={expandedId === notif.id}
                onExpand={() => setExpandedId(expandedId === notif.id ? null : notif.id)}
                onMarkRead={() => markNotifReadMutation.mutate(notif.id)}
                staleCapsuleCount={notif.notification_type === "capsule_updated" ? staleCapsuleCount : undefined}
              />
            ))
          )}
        </div>
      ) : (
        /* Message list */
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
                  Ask your agent to send a message: &quot;Message Dr. Lee about my appointment&quot;
                </p>
              )}
            </div>
          ) : (
            messages.map((msg) => (
              <MessageRow
                key={msg.id}
                msg={msg}
                isSent={isSentTab}
                expanded={expandedId === msg.id}
                onExpand={() => handleExpand(msg, isSentTab)}
                onDelete={() => deleteMutation.mutate(msg.id)}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
}
