"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { useQuery } from "@tanstack/react-query";
import { api, type User, getUnreadCount } from "@/lib/api";
import { PodSwitcher } from "./PodSwitcher";
import { UserAvatar } from "./UserAvatar";

interface NavItem {
  href: string;
  label: string;
  icon: React.ReactNode;
  requiresSetup?: boolean;
}

interface NavSection {
  label: string;
  items: NavItem[];
  requiresSetup?: boolean;
}

const NAV_SECTIONS: NavSection[] = [
  {
    label: "Core",
    items: [
      {
        href: "",
        label: "Dashboard",
        icon: (
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>
            <rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>
          </svg>
        ),
      },
      {
        href: "/chat",
        label: "Ask My Agent",
        icon: (
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
        ),
      },
      {
        href: "/vault",
        label: "Memories",
        requiresSetup: true,
        icon: (
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0110 0v4"/>
          </svg>
        ),
      },
    ],
  },
  {
    label: "Social",
    requiresSetup: true,
    items: [
      {
        href: "/connections",
        label: "People",
        requiresSetup: true,
        icon: (
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>
            <path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>
          </svg>
        ),
      },
      {
        href: "/networks",
        label: "Groups",
        requiresSetup: true,
        icon: (
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="5" r="3"/><circle cx="5" cy="19" r="3"/><circle cx="19" cy="19" r="3"/>
            <line x1="12" y1="8" x2="5" y2="16"/><line x1="12" y1="8" x2="19" y2="16"/>
          </svg>
        ),
      },
      {
        href: "/inbox",
        label: "Inbox",
        requiresSetup: true,
        icon: (
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/>
            <path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>
          </svg>
        ),
      },
    ],
  },
  {
    label: "Explore",
    items: [
      {
        href: "/discover",
        label: "Discover",
        icon: (
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
        ),
      },
      {
        href: "/services",
        label: "Services",
        requiresSetup: true,
        icon: (
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M20 7h-9"/><path d="M14 17H5"/>
            <circle cx="17" cy="17" r="3"/><circle cx="7" cy="7" r="3"/>
          </svg>
        ),
      },
    ],
  },
  {
    label: "Safety",
    requiresSetup: true,
    items: [
      {
        href: "/emergency/beacon",
        label: "Emergency Medical ID",
        requiresSetup: true,
        icon: (
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
            <line x1="12" y1="8" x2="12" y2="12"/>
            <line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
        ),
      },
    ],
  },
  {
    label: "Automation",
    requiresSetup: true,
    items: [
      {
        href: "/timeline",
        label: "Timeline",
        requiresSetup: true,
        icon: (
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
          </svg>
        ),
      },
      {
        href: "/audit",
        label: "Activity Log",
        requiresSetup: true,
        icon: (
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
            <path d="M9 12l2 2 4-4"/>
          </svg>
        ),
      },
    ],
  },
];

interface SidebarProps {
  user: User;
  isOpen: boolean;
  onClose: () => void;
}

export function Sidebar({ user, isOpen, onClose }: SidebarProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { logout } = useAuth();
  const base = `/${user.id}`;

  const { data: capsules } = useQuery({
    queryKey: ["capsules", user.id],
    queryFn: () => api.listCapsules(user.id),
  });
  const isNewUser = (capsules?.length ?? 0) === 0;

  const { data: inboxUnread } = useQuery({
    queryKey: ["inboxUnreadCount", user.id],
    queryFn: () => getUnreadCount(user.id),
    refetchInterval: 10_000,
    enabled: !isNewUser,
  });
  const inboxUnreadCount = inboxUnread ?? 0;

  const handleLogout = () => {
    logout();
    router.push("/");
  };

  const handleNavClick = () => {
    onClose();
  };

  const sidebarInner = (
    <aside className="w-56 bg-card/50 backdrop-blur-sm border-r border-card-border flex flex-col h-full">
      {/* Brand + user header */}
      <div className="p-4 border-b border-card-border">
        <div className="flex items-center justify-between mb-2.5">
          <Link
            href="/"
            onClick={handleNavClick}
            className="flex items-center gap-2 hover:opacity-80 transition-opacity"
          >
            <div className="w-7 h-7 rounded-lg bg-accent flex items-center justify-center shrink-0">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#09090b" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
              </svg>
            </div>
            <span className="font-bold text-sm tracking-tight">TrustMesh</span>
          </Link>
          <Link
            href={`/${user.id}/profile`}
            onClick={handleNavClick}
            className="hover:opacity-80 transition-opacity shrink-0 ml-2"
            aria-label="Go to profile"
          >
            <UserAvatar user={user} size="sm" />
          </Link>
        </div>
        <Link
          href={`/${user.id}/profile`}
          onClick={handleNavClick}
          className="block hover:opacity-80 transition-opacity"
        >
          <p className="text-xs font-semibold truncate leading-tight">{user.display_name}</p>
          <p className="text-[10px] text-muted-foreground truncate leading-snug mt-0.5">
            {user.username ? `@${user.username}` : "Private"}
          </p>
        </Link>
      </div>

      {/* Pod Switcher */}
      {!isNewUser && (
        <div className="px-3 py-2 border-b border-card-border">
          <PodSwitcher userName={user.display_name} />
        </div>
      )}

      {/* Navigation */}
      <nav className="flex-1 p-2 overflow-y-auto space-y-3">
        {NAV_SECTIONS.map((section) => {
          // Hide setup-dependent sections for new users
          const visibleItems = section.items.filter((item) => !item.requiresSetup || !isNewUser);
          if (visibleItems.length === 0) return null;
          if (section.requiresSetup && isNewUser) return null;

          return (
            <div key={section.label}>
              <p className="px-3 mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/50">
                {section.label}
              </p>
              <div className="space-y-0.5">
                {visibleItems.map((item) => {
                  const href = `${base}${item.href}`;
                  const isActive = item.href === ""
                    ? pathname === base || pathname === `${base}/`
                    : pathname.startsWith(href);
                  return (
                    <Link
                      key={item.href}
                      href={href}
                      onClick={handleNavClick}
                      className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs transition-all ${
                        item.href === "/emergency/beacon"
                          ? isActive
                            ? "bg-red-900/40 text-red-400 font-medium"
                            : "text-red-400/70 hover:text-red-400 hover:bg-red-950/40"
                          : isActive
                          ? "bg-accent/10 text-accent font-medium"
                          : "text-muted-foreground hover:text-foreground hover:bg-card-hover"
                      }`}
                    >
                      <span className={item.href === "/emergency/beacon" ? "text-red-400/80" : isActive ? "text-accent" : "text-muted-foreground/70"}>{item.icon}</span>
                      <span className="flex-1">{item.label}</span>
                      {item.href === "/inbox" && inboxUnreadCount > 0 && (
                        <span className="flex items-center justify-center min-w-[16px] h-[16px] px-1 text-[9px] font-bold text-white bg-danger rounded-full">
                          {inboxUnreadCount > 99 ? "99+" : inboxUnreadCount}
                        </span>
                      )}
                    </Link>
                  );
                })}
              </div>
            </div>
          );
        })}
      </nav>

      {/* Bottom */}
      <div className="p-2 border-t border-card-border space-y-0.5">
        <Link
          href={`/${user.id}/onboard`}
          onClick={handleNavClick}
          className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs transition-all ${
            pathname.startsWith(`${base}/onboard`)
              ? "bg-accent/10 text-accent font-medium"
              : "text-muted-foreground hover:text-foreground hover:bg-card-hover"
          }`}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-muted-foreground/70">
            <path d="M12 2a2 2 0 0 1 2 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 0 1 7 7h1a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1h-1.27A7 7 0 0 1 14 22h-4a7 7 0 0 1-6.73-3H2a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1h1a7 7 0 0 1 7-7h1V5.73c-.6-.34-1-.99-1-1.73a2 2 0 0 1 2-2z"/>
            <circle cx="10" cy="16" r="1"/><circle cx="14" cy="16" r="1"/>
          </svg>
          <span className="flex-1">Train Agent</span>
        </Link>
        {!isNewUser && (
          <Link
            href="/graph"
            onClick={handleNavClick}
            className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs transition-all ${
              pathname === "/graph"
                ? "bg-accent/10 text-accent font-medium"
                : "text-muted-foreground hover:text-foreground hover:bg-card-hover"
            }`}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-muted-foreground/70">
              <circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/>
              <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
            </svg>
            Trust Map
          </Link>
        )}
        <Link
          href={`/${user.id}/pod`}
          onClick={handleNavClick}
          className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs transition-all ${
            pathname.startsWith(`${base}/pod`)
              ? "bg-accent/10 text-accent font-medium"
              : "text-muted-foreground hover:text-foreground hover:bg-card-hover"
          }`}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-muted-foreground/70">
            <circle cx="12" cy="12" r="3"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M4.93 4.93a10 10 0 0 0 0 14.14"/>
            <path d="M15.54 8.46a5 5 0 0 1 0 7.07M8.46 8.46a5 5 0 0 0 0 7.07"/>
          </svg>
          Settings
        </Link>
        <button
          onClick={handleLogout}
          className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs text-muted-foreground hover:text-danger hover:bg-danger-dim transition-all"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>
          </svg>
          Log Out
        </button>
      </div>
    </aside>
  );

  return (
    <>
      {/* Desktop */}
      <div className="hidden md:flex h-screen sticky top-0 shrink-0">
        {sidebarInner}
      </div>

      {/* Mobile drawer */}
      {isOpen && (
        <div className="md:hidden fixed inset-0 z-50 flex">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={onClose}
            aria-hidden="true"
          />
          <div className="relative flex h-full w-56 shrink-0 shadow-2xl">
            <button
              onClick={onClose}
              className="absolute top-3 right-3 z-10 p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-card-hover transition-all"
              aria-label="Close sidebar"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
            {sidebarInner}
          </div>
        </div>
      )}
    </>
  );
}
