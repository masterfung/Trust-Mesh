"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { useQuery } from "@tanstack/react-query";
import { api, type User } from "@/lib/api";
import { PodSwitcher } from "./PodSwitcher";
import { UserAvatar } from "./UserAvatar";

interface NavItem {
  href: string;
  label: string;
  icon: React.ReactNode;
  requiresSetup?: boolean; // Hidden for new users with 0 capsules
}

const NAV_ITEMS: NavItem[] = [
  {
    href: "",
    label: "Dashboard",
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>
        <rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>
      </svg>
    ),
  },
  {
    href: "/onboard",
    label: "Set Up Agent",
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 2a2 2 0 0 1 2 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 0 1 7 7h1a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1h-1.27A7 7 0 0 1 14 22h-4a7 7 0 0 1-6.73-3H2a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1h1a7 7 0 0 1 7-7h1V5.73c-.6-.34-1-.99-1-1.73a2 2 0 0 1 2-2z"/>
        <circle cx="10" cy="16" r="1"/><circle cx="14" cy="16" r="1"/>
      </svg>
    ),
  },
  {
    href: "/chat",
    label: "Ask Agents",
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
      </svg>
    ),
  },
  {
    href: "/vault",
    label: "Knowledge Vault",
    requiresSetup: true,
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0110 0v4"/>
      </svg>
    ),
  },
  {
    href: "/networks",
    label: "Networks",
    requiresSetup: true,
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="5" r="3"/><circle cx="5" cy="19" r="3"/><circle cx="19" cy="19" r="3"/>
        <line x1="12" y1="8" x2="5" y2="16"/><line x1="12" y1="8" x2="19" y2="16"/>
      </svg>
    ),
  },
  {
    href: "/connections",
    label: "Connections",
    requiresSetup: true,
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>
        <line x1="19" y1="8" x2="19" y2="14"/><line x1="22" y1="11" x2="16" y2="11"/>
      </svg>
    ),
  },
  {
    href: "/discover",
    label: "Discover",
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
      </svg>
    ),
  },
  {
    href: "/services",
    label: "Services",
    requiresSetup: true,
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M20 7h-9"/><path d="M14 17H5"/>
        <circle cx="17" cy="17" r="3"/><circle cx="7" cy="7" r="3"/>
      </svg>
    ),
  },
  {
    href: "/timeline",
    label: "Timeline",
    requiresSetup: true,
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
      </svg>
    ),
  },
  {
    href: "/pod",
    label: "Pod",
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>
        <polyline points="3.27 6.96 12 12.01 20.73 6.96"/>
        <line x1="12" y1="22.08" x2="12" y2="12"/>
      </svg>
    ),
  },
  {
    href: "/audit",
    label: "Audit Log",
    requiresSetup: true,
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
        <path d="M9 12l2 2 4-4"/>
      </svg>
    ),
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

  // Check if user has capsules to determine new-user state
  const { data: capsules } = useQuery({
    queryKey: ["capsules", user.id],
    queryFn: () => api.listCapsules(user.id),
  });
  const isNewUser = (capsules?.length ?? 0) === 0;

  // Filter nav items: hide setup-dependent items for new users
  const visibleItems = NAV_ITEMS.filter((item) => !item.requiresSetup || !isNewUser);

  const handleLogout = () => {
    logout();
    router.push("/");
  };

  // Called when a nav link is clicked on mobile — close the drawer
  const handleNavClick = () => {
    onClose();
  };

  const sidebarInner = (
    <aside className="w-60 bg-card/50 backdrop-blur-sm border-r border-card-border flex flex-col h-full">
      {/* Unified brand + user header */}
      <div className="p-4 border-b border-card-border">
        {/* Top row: shield + TrustMesh left, avatar right */}
        <div className="flex items-center justify-between mb-2.5">
          <Link
            href="/"
            onClick={handleNavClick}
            className="flex items-center gap-2 hover:opacity-80 transition-opacity"
          >
            <div className="w-8 h-8 rounded-lg bg-accent flex items-center justify-center shrink-0">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#09090b" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
              </svg>
            </div>
            <span className="font-bold text-base tracking-tight">TrustMesh</span>
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
        {/* Second row: display name + handle */}
        <Link
          href={`/${user.id}/profile`}
          onClick={handleNavClick}
          className="block hover:opacity-80 transition-opacity"
        >
          <p className="text-sm font-semibold truncate leading-tight">{user.display_name}</p>
          <p className="text-xs text-muted-foreground truncate leading-snug mt-0.5">
            {user.username ? `@${user.username}` : "Private"}
          </p>
        </Link>
      </div>

      {/* Pod Switcher — only show when user has set up their pod */}
      {!isNewUser && (
        <div className="px-3 py-2 border-b border-card-border">
          <PodSwitcher userName={user.display_name} />
        </div>
      )}

      {/* Navigation */}
      <nav className="flex-1 p-3 space-y-0.5 overflow-y-auto">
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
              className={`flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm transition-all ${
                isActive
                  ? "bg-accent/10 text-accent font-medium shadow-sm"
                  : "text-muted-foreground hover:text-foreground hover:bg-card-hover"
              }`}
            >
              <span className={isActive ? "text-accent" : "text-muted-foreground"}>{item.icon}</span>
              {item.label}
            </Link>
          );
        })}
      </nav>

      {/* Bottom */}
      <div className="p-3 border-t border-card-border space-y-0.5">
        {!isNewUser && (
          <Link
            href="/graph"
            onClick={handleNavClick}
            className="flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm text-muted-foreground hover:text-foreground hover:bg-card-hover transition-all"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/>
              <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
            </svg>
            Trust Graph
          </Link>
        )}
        <button
          onClick={handleLogout}
          className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm text-muted-foreground hover:text-danger hover:bg-danger-dim transition-all"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>
          </svg>
          Log Out
        </button>
      </div>
    </aside>
  );

  return (
    <>
      {/* Desktop: always-visible sticky sidebar */}
      <div className="hidden md:flex h-screen sticky top-0 shrink-0">
        {sidebarInner}
      </div>

      {/* Mobile: slide-in drawer with backdrop overlay */}
      {isOpen && (
        <div className="md:hidden fixed inset-0 z-50 flex">
          {/* Semi-transparent backdrop — click to close */}
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={onClose}
            aria-hidden="true"
          />

          {/* Drawer panel slides in from the left */}
          <div className="relative flex h-full w-60 shrink-0 shadow-2xl">
            {/* X close button — top-right corner of the drawer */}
            <button
              onClick={onClose}
              className="absolute top-3 right-3 z-10 p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-card-hover transition-all focus:outline-none focus:ring-2 focus:ring-accent/50"
              aria-label="Close sidebar"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18"/>
                <line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
            {sidebarInner}
          </div>
        </div>
      )}
    </>
  );
}
