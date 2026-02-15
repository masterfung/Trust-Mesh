"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, Notification as NotificationType, ContextMode } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Sidebar } from "@/components/Sidebar";
import { useParams, useRouter } from "next/navigation";

// -- Notification type icon mapping --

function NotificationIcon({ type }: { type: string }) {
  const iconClass = "w-4 h-4 shrink-0";

  switch (type) {
    case "emergency_access":
      return (
        <svg className={iconClass} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
      );
    case "connection_request":
    case "connection_accepted":
      return (
        <svg className={iconClass} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
          <circle cx="9" cy="7" r="4" />
          <line x1="19" y1="8" x2="19" y2="14" />
          <line x1="22" y1="11" x2="16" y2="11" />
        </svg>
      );
    case "network_invite":
    case "network_joined":
      return (
        <svg className={iconClass} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="5" r="3" />
          <circle cx="5" cy="19" r="3" />
          <circle cx="19" cy="19" r="3" />
          <line x1="12" y1="8" x2="5" y2="16" />
          <line x1="12" y1="8" x2="19" y2="16" />
        </svg>
      );
    case "query_received":
    case "query_response":
      return (
        <svg className={iconClass} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
      );
    case "capsule_shared":
    case "capsule_update":
      return (
        <svg className={iconClass} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
          <path d="M7 11V7a5 5 0 0110 0v4" />
        </svg>
      );
    case "task_complete":
      return (
        <svg className={iconClass} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
          <polyline points="22 4 12 14.01 9 11.01" />
        </svg>
      );
    default:
      return (
        <svg className={iconClass} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
      );
  }
}

// -- Time ago helper --

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
  const weeks = Math.floor(days / 7);
  if (weeks < 4) return `${weeks}w ago`;
  return date.toLocaleDateString();
}

// -- Context Switcher --

const PERSON_CONTEXTS: { value: ContextMode; label: string; icon: string }[] = [
  { value: "all", label: "All", icon: "◉" },
  { value: "work", label: "Work", icon: "💼" },
  { value: "personal", label: "Personal", icon: "🏠" },
];

const ORG_CONTEXTS: { value: ContextMode; label: string; icon: string }[] = [
  { value: "all", label: "All", icon: "◉" },
  { value: "work", label: "Internal", icon: "🔒" },
];

function ContextSwitcher({ userId, currentContext, userType }: { userId: string; currentContext: ContextMode; userType: string }) {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: (ctx: ContextMode) => api.switchContext(userId, ctx),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["user", userId] });
      queryClient.invalidateQueries({ queryKey: ["networks"] });
      queryClient.invalidateQueries({ queryKey: ["connections"] });
    },
  });

  const options = userType === "person" ? PERSON_CONTEXTS : ORG_CONTEXTS;

  return (
    <div className="flex items-center gap-1 bg-card rounded-lg border border-card-border p-0.5">
      {options.map((opt) => (
        <button
          key={opt.value}
          onClick={() => mutation.mutate(opt.value)}
          className={`px-2.5 py-1 rounded-md text-xs font-medium transition-all ${
            currentContext === opt.value
              ? "bg-accent text-accent-fg shadow-sm"
              : "text-muted-foreground hover:text-foreground hover:bg-hover"
          }`}
          title={`Switch to ${opt.label} mode`}
        >
          <span className="mr-1">{opt.icon}</span>
          {opt.label}
        </button>
      ))}
    </div>
  );
}

// -- Notification color for type --

function notificationTypeColor(type: string): string {
  switch (type) {
    case "emergency_access":
      return "text-danger";
    case "connection_request":
    case "connection_accepted":
      return "text-accent";
    case "network_invite":
    case "network_joined":
      return "text-accent";
    case "query_received":
    case "query_response":
      return "text-sky-400";
    case "capsule_shared":
    case "capsule_update":
      return "text-warning";
    case "task_complete":
      return "text-success";
    default:
      return "text-muted-foreground";
  }
}

// -- Notification Bell Component --

function NotificationBell({ userId }: { userId: string }) {
  const [open, setOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const queryClient = useQueryClient();
  const router = useRouter();

  const { data: unreadData } = useQuery({
    queryKey: ["unreadCount", userId],
    queryFn: () => api.getUnreadCount(userId),
    refetchInterval: 30_000,
  });

  // SSE real-time notification stream
  const openRef = useRef(open);
  useEffect(() => {
    openRef.current = open;
  }, [open]);

  useEffect(() => {
    const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    const eventSource = new EventSource(`${API_BASE}/api/users/${userId}/notifications/stream`);
    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.count !== undefined) {
          queryClient.setQueryData(["unreadCount", userId], { count: data.count });
          // Only refetch notification list if dropdown is NOT open (prevents flicker)
          if (data.count > 0 && !openRef.current) {
            queryClient.invalidateQueries({ queryKey: ["notifications", userId] });
          }
        }
      } catch {}
    };
    eventSource.onerror = () => {
      eventSource.close();
    };
    return () => eventSource.close();
  }, [userId, queryClient]);

  const { data: notifications, isLoading: notificationsLoading } = useQuery({
    queryKey: ["notifications", userId],
    queryFn: () => api.listNotifications(userId),
    enabled: open,
  });

  const markAllReadMutation = useMutation({
    mutationFn: () => api.markAllNotificationsRead(userId),
    onSuccess: () => {
      // Optimistically update local state instead of refetching (prevents flicker)
      queryClient.setQueryData(["unreadCount", userId], { count: 0 });
      queryClient.setQueryData(
        ["notifications", userId],
        (old: NotificationType[] | undefined) =>
          old?.map((n) => ({ ...n, is_read: true })) ?? []
      );
    },
  });

  const markOneMutation = useMutation({
    mutationFn: (notificationId: string) => api.markNotificationRead(notificationId),
    onSuccess: (_data, notificationId) => {
      queryClient.setQueryData(["unreadCount", userId], (old: { count: number } | undefined) => ({
        count: Math.max(0, (old?.count ?? 1) - 1),
      }));
      queryClient.setQueryData(
        ["notifications", userId],
        (old: NotificationType[] | undefined) =>
          old?.map((n) => (n.id === notificationId ? { ...n, is_read: true } : n)) ?? []
      );
    },
  });

  const unreadCount = unreadData?.count ?? 0;

  // Close dropdown on outside click
  const handleClickOutside = useCallback((e: MouseEvent) => {
    if (
      dropdownRef.current &&
      !dropdownRef.current.contains(e.target as Node) &&
      buttonRef.current &&
      !buttonRef.current.contains(e.target as Node)
    ) {
      setOpen(false);
    }
  }, []);

  useEffect(() => {
    if (open) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open, handleClickOutside]);

  // Close on Escape
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    if (open) {
      document.addEventListener("keydown", handleEsc);
    }
    return () => document.removeEventListener("keydown", handleEsc);
  }, [open]);

  const handleNotificationClick = (notification: NotificationType) => {
    if (!notification.is_read) {
      markOneMutation.mutate(notification.id);
    }
    setOpen(false);
    // Navigate based on notification type
    const base = `/${userId}`;
    switch (notification.notification_type) {
      case "emergency_access":
        router.push(`${base}/audit`);
        break;
      case "query_received":
      case "query_response":
        router.push(`${base}/chat`);
        break;
      case "join_request":
      case "network_invite":
      case "network_joined":
        router.push(`${base}/networks`);
        break;
      case "connection_request":
      case "connection_accepted":
        router.push(`${base}/connections`);
        break;
      case "task_complete":
        router.push(base); // dashboard
        break;
      case "capsule_shared":
      case "capsule_update":
        router.push(`${base}/vault`);
        break;
      default:
        router.push(base);
    }
  };

  return (
    <div className="relative">
      <button
        ref={buttonRef}
        onClick={() => setOpen((prev) => !prev)}
        className="relative p-2 rounded-xl text-muted-foreground hover:text-foreground hover:bg-card-hover transition-all focus:outline-none focus:ring-2 focus:ring-accent/50"
        aria-label={`Notifications${unreadCount > 0 ? `, ${unreadCount} unread` : ""}`}
        aria-expanded={open}
        aria-haspopup="true"
      >
        {/* Bell icon */}
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>

        {/* Unread badge */}
        {unreadCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 flex items-center justify-center min-w-[18px] h-[18px] px-1 text-[10px] font-bold text-white bg-danger rounded-full ring-2 ring-background animate-pulse">
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </button>

      {/* Dropdown */}
      {open && (
        <div
          ref={dropdownRef}
          className="absolute right-0 top-full mt-2 w-96 max-h-[480px] bg-card border border-card-border rounded-2xl shadow-2xl shadow-black/40 overflow-hidden z-50 flex flex-col"
          role="menu"
          aria-label="Notifications"
        >
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-card-border bg-card/80 backdrop-blur-sm">
            <h3 className="text-sm font-semibold text-foreground">Notifications</h3>
            {unreadCount > 0 && (
              <button
                onClick={() => markAllReadMutation.mutate()}
                disabled={markAllReadMutation.isPending}
                className="text-xs text-accent hover:text-accent-hover transition-colors disabled:opacity-50"
              >
                {markAllReadMutation.isPending ? "Marking..." : "Mark all read"}
              </button>
            )}
          </div>

          {/* Notification list */}
          <div className="flex-1 overflow-y-auto">
            {notificationsLoading ? (
              <div className="flex items-center justify-center py-12">
                <div className="text-muted-foreground text-sm animate-pulse">Loading notifications...</div>
              </div>
            ) : !notifications || notifications.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 px-4">
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-muted-foreground mb-2">
                  <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                  <path d="M13.73 21a2 2 0 0 1-3.46 0" />
                </svg>
                <p className="text-sm text-muted-foreground">No notifications yet</p>
              </div>
            ) : (
              notifications.map((notification) => (
                <button
                  key={notification.id}
                  onClick={() => handleNotificationClick(notification)}
                  className={`w-full text-left px-4 py-3 border-b border-card-border/50 hover:bg-card-hover transition-colors flex gap-3 ${
                    !notification.is_read ? "bg-accent-glow/30" : ""
                  }`}
                  role="menuitem"
                >
                  {/* Type icon */}
                  <div className={`mt-0.5 ${notificationTypeColor(notification.notification_type)}`}>
                    <NotificationIcon type={notification.notification_type} />
                  </div>

                  {/* Content */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-start justify-between gap-2">
                      <p className={`text-sm leading-tight ${!notification.is_read ? "font-semibold text-foreground" : "text-muted-foreground"}`}>
                        {notification.title}
                      </p>
                      {!notification.is_read && (
                        <span className="w-2 h-2 rounded-full bg-accent shrink-0 mt-1" />
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2 leading-relaxed">
                      {notification.body}
                    </p>
                    <p className="text-[10px] text-muted-foreground mt-1">
                      {timeAgo(notification.created_at)}
                    </p>
                  </div>
                </button>
              ))
            )}
          </div>

          {/* Footer */}
          {notifications && notifications.length > 0 && (
            <div className="px-4 py-2.5 border-t border-card-border bg-card/80 backdrop-blur-sm text-center">
              <span className="text-xs text-muted-foreground">
                {notifications.length} notification{notifications.length !== 1 ? "s" : ""}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// -- Main Layout --

export default function UserLayout({ children }: { children: React.ReactNode }) {
  const params = useParams();
  const router = useRouter();
  const userId = params.userId as string;
  const { user: authUser, isLoading: authLoading } = useAuth();

  const { data: user, isLoading } = useQuery({
    queryKey: ["user", userId],
    queryFn: () => api.getUser(userId),
  });

  // Redirect to landing if not authenticated
  useEffect(() => {
    if (!authLoading && !authUser) {
      router.push("/");
    }
  }, [authUser, authLoading, router]);

  // Redirect if trying to access another user's dashboard
  useEffect(() => {
    if (!authLoading && authUser && authUser.id !== userId) {
      router.push(`/${authUser.id}`);
    }
  }, [authUser, authLoading, userId, router]);

  if (authLoading || isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-muted-foreground animate-pulse">Loading...</div>
      </div>
    );
  }

  if (!authUser) {
    return null; // Will redirect
  }

  if (!user) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-danger">User not found</div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen">
      <Sidebar user={user} />
      <div className="flex-1 flex flex-col overflow-auto">
        {/* Top Bar */}
        <header className="sticky top-0 z-40 flex items-center justify-between px-4 md:px-8 h-14 border-b border-card-border bg-background/80 backdrop-blur-md shrink-0">
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">Welcome back,</span>
            <span className="text-sm font-semibold text-foreground">{user.display_name}</span>
          </div>
          <div className="flex items-center gap-3">
            <ContextSwitcher userId={userId} currentContext={(user.active_context as ContextMode) || "all"} userType={user.user_type || "person"} />
            <NotificationBell userId={userId} />
          </div>
        </header>

        {/* Main Content */}
        <main className="flex-1 p-4 md:p-8">{children}</main>
      </div>
    </div>
  );
}
