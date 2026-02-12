"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { User } from "@/lib/api";

const NAV_ITEMS = [
  { href: "", label: "Dashboard", icon: "D" },
  { href: "/chat", label: "Chat", icon: "Q" },
  { href: "/vault", label: "Vault", icon: "V" },
  { href: "/networks", label: "Networks", icon: "N" },
  { href: "/connections", label: "Connections", icon: "C" },
];

export function Sidebar({ user }: { user: User }) {
  const pathname = usePathname();
  const base = `/${user.id}`;

  return (
    <aside className="w-56 bg-card border-r border-card-border flex flex-col h-screen sticky top-0">
      <Link href="/" className="block p-4 border-b border-card-border hover:bg-card-border/30">
        <h1 className="text-accent font-bold text-lg">TrustMesh</h1>
        <p className="text-xs text-muted mt-0.5">Trust-Aware Knowledge Sharing</p>
      </Link>

      <div className="p-4 border-b border-card-border">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-full bg-accent-dim flex items-center justify-center text-white font-bold text-sm">
            {user.display_name[0]}
          </div>
          <div>
            <p className="text-sm font-medium">{user.display_name}</p>
            <p className="text-xs text-muted">@{user.username}</p>
          </div>
        </div>
      </div>

      <nav className="flex-1 p-2">
        {NAV_ITEMS.map((item) => {
          const href = `${base}${item.href}`;
          const isActive = item.href === ""
            ? pathname === base || pathname === `${base}/`
            : pathname.startsWith(href);
          return (
            <Link
              key={item.href}
              href={href}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm mb-1 transition-colors ${
                isActive
                  ? "bg-accent/15 text-accent font-medium"
                  : "text-muted hover:text-foreground hover:bg-card-border/30"
              }`}
            >
              <span className="w-5 h-5 flex items-center justify-center rounded bg-card-border text-xs font-bold">
                {item.icon}
              </span>
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="p-2 border-t border-card-border">
        <Link
          href="/graph"
          className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-muted hover:text-foreground hover:bg-card-border/30"
        >
          <span className="w-5 h-5 flex items-center justify-center rounded bg-card-border text-xs font-bold">G</span>
          Trust Graph
        </Link>
      </div>
    </aside>
  );
}
