"use client";

import { useAuth } from "@/lib/auth";
import Link from "next/link";
import { useRouter } from "next/navigation";

export default function Home() {
  const { user: authUser, logout } = useAuth();
  const router = useRouter();

  return (
    <div className="min-h-screen flex flex-col">
      {/* Top Nav */}
      <nav className="flex items-center justify-between px-4 sm:px-6 py-3">
        <span className="text-base font-bold tracking-tight text-gradient">TrustMesh</span>
        <div className="flex items-center gap-2 sm:gap-3">
          <Link
            href="/doc"
            className="hidden sm:block text-xs text-muted-foreground hover:text-foreground transition-colors px-2 py-1.5 rounded-lg hover:bg-card"
          >
            Docs
          </Link>
          <a
            href="http://localhost:8100"
            target="_blank"
            rel="noopener noreferrer"
            className="hidden sm:inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors px-2 py-1.5 rounded-lg hover:bg-card"
          >
            Registry
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="opacity-60">
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
              <polyline points="15 3 21 3 21 9" />
              <line x1="10" y1="14" x2="21" y2="3" />
            </svg>
          </a>
          {authUser ? (
            <>
              <button
                onClick={() => router.push(`/${authUser.id}`)}
                className="px-3 sm:px-4 py-1.5 bg-accent hover:bg-accent-hover text-accent-fg font-medium rounded-lg text-xs sm:text-sm transition-all"
              >
                Dashboard
              </button>
              <button
                onClick={() => logout()}
                className="px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground rounded-lg hover:bg-card transition-colors"
              >
                Log Out
              </button>
            </>
          ) : (
            <>
              <Link
                href="/login"
                className="px-3 sm:px-4 py-1.5 text-xs sm:text-sm text-muted-foreground hover:text-foreground font-medium rounded-lg hover:bg-card transition-colors"
              >
                Log In
              </Link>
              <Link
                href="/signup"
                className="px-3 sm:px-4 py-1.5 bg-accent hover:bg-accent-hover text-accent-fg font-medium rounded-lg text-xs sm:text-sm transition-all"
              >
                Sign Up
              </Link>
            </>
          )}
        </div>
      </nav>

      {/* Hero */}
      <div className="flex-1 flex flex-col items-center justify-center px-4 sm:px-6 py-8 md:py-16">
        <div className="text-center mb-8 md:mb-12">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-accent/10 border border-accent/20 text-accent text-xs font-medium mb-6">
            <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
            Powered by Gemini 3.1 Pro
          </div>
          <h1 className="text-4xl sm:text-5xl md:text-6xl font-bold tracking-tight mb-4">
            <span className="text-gradient">TrustMesh</span>
          </h1>
          <p className="text-base sm:text-lg md:text-xl text-foreground max-w-2xl mx-auto leading-relaxed font-medium">
            Share what matters with people you trust.
          </p>
          <p className="text-sm sm:text-base text-muted-foreground max-w-xl mx-auto leading-relaxed mt-3">
            Everyone gets a private collection of memories and an AI assistant powered by Gemini 3.1 Pro.
            Your assistant works with people you trust — sharing what&apos;s needed,
            protecting everything else. Simple to start. Zero configuration.
          </p>
        </div>

        {/* Feature Pills */}
        <div className="flex flex-wrap justify-center gap-2 sm:gap-3 mb-8 md:mb-12">
          {[
            { icon: "🔐", label: "Your data, encrypted" },
            { icon: "🤖", label: "Personal AI agent" },
            { icon: "👥", label: "You choose who sees what" },
            { icon: "🛡️", label: "Protected by AI security", href: "https://trymighty.ai" },
          ].map((f) =>
            "href" in f && f.href ? (
              <a
                key={f.label}
                href={f.href}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2 px-3 sm:px-4 py-1.5 sm:py-2 rounded-full bg-card border border-card-border text-xs sm:text-sm text-muted-foreground hover:border-red-500/40 hover:text-red-400 transition-colors"
              >
                <span>{f.icon}</span>
                <span>{f.label}</span>
              </a>
            ) : (
              <div
                key={f.label}
                className="flex items-center gap-2 px-3 sm:px-4 py-1.5 sm:py-2 rounded-full bg-card border border-card-border text-xs sm:text-sm text-muted-foreground"
              >
                <span>{f.icon}</span>
                <span>{f.label}</span>
              </div>
            )
          )}
        </div>

        {/* CTA Buttons */}
        <div className="flex flex-col sm:flex-row gap-3 mb-8 md:mb-12">
          <Link
            href="/signup"
            className="inline-flex items-center justify-center gap-2 px-6 py-2.5 rounded-xl bg-accent hover:bg-accent-hover text-accent-fg text-sm font-semibold transition-all hover:shadow-lg hover:shadow-accent/20"
          >
            Get started free
          </Link>
          <Link
            href="/about"
            className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl bg-card border border-card-border text-sm text-muted-foreground hover:text-foreground hover:border-accent/50 transition-all"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>
            </svg>
            Why TrustMesh?
          </Link>
          <Link
            href="/graph"
            className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl bg-card border border-card-border text-sm text-muted-foreground hover:text-foreground hover:border-accent/50 transition-all"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="5" r="3"/><circle cx="5" cy="19" r="3"/><circle cx="19" cy="19" r="3"/>
              <line x1="12" y1="8" x2="5" y2="16"/><line x1="12" y1="8" x2="19" y2="16"/>
            </svg>
            View Trust Graph
          </Link>
        </div>
      </div>

      {/* Footer */}
      <footer className="py-4 sm:py-6 px-4 border-t border-card-border text-center space-y-1">
        <p className="text-xs text-muted-foreground">
          Built with love by{" "}
          <a href="https://github.com/masterfung" target="_blank" rel="noopener noreferrer" className="text-accent hover:text-accent-hover transition-colors">
            @masterfung
          </a>{" "}
          &middot; Powered by Gemini 3.1 Pro
        </p>
        <p className="text-xs text-muted-foreground">
          End-to-end encrypted &middot;{" "}
          <a href="https://trymighty.ai" target="_blank" rel="noopener noreferrer" className="text-red-400 hover:text-red-300 transition-colors">
            Protected by AI security
          </a>
        </p>
      </footer>
    </div>
  );
}
