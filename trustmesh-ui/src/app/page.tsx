"use client";

import { useState, useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type User } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";

function validatePasswordComplexity(pw: string): string | null {
  if (pw.length < 16) return "Password must be at least 16 characters";
  if (!/[A-Z]/.test(pw)) return "Must contain an uppercase letter";
  if (!/[a-z]/.test(pw)) return "Must contain a lowercase letter";
  if (!/[0-9]/.test(pw)) return "Must contain a digit";
  if (!/[^A-Za-z0-9]/.test(pw)) return "Must contain a special character (!@#$%^&* etc.)";
  return null;
}

function validateName(name: string): string | null {
  if (!name.trim()) return null;
  if (!/^[A-Za-z][A-Za-z \-'.]+$/.test(name.trim())) return "Letters only (spaces, hyphens, apostrophes OK)";
  if (name.trim().split(/\s+/).length < 2) return "Please enter first and last name";
  return null;
}

export default function Home() {
  const { user: authUser, isLoading: authLoading, logout } = useAuth();
  const router = useRouter();
  const [authMode, setAuthMode] = useState<"none" | "login" | "signup">("none");

  // Clear any stale pod URL on home page — user's pod is always the default (8000)
  useEffect(() => {
    if (typeof window !== "undefined") {
      localStorage.removeItem("trustmesh_pod_url");
    }
  }, []);

  if (authLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-muted-foreground animate-pulse">Loading...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col">
      {/* Top Nav — auth buttons on the right */}
      <nav className="flex items-center justify-between px-4 sm:px-6 py-3">
        <div className="flex items-center gap-2">
          <span className="text-base font-bold tracking-tight text-gradient">TrustMesh</span>
        </div>
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
              <button
                onClick={() => setAuthMode("login")}
                className="px-3 sm:px-4 py-1.5 text-xs sm:text-sm text-muted-foreground hover:text-foreground font-medium rounded-lg hover:bg-card transition-colors"
              >
                Log In
              </button>
              <button
                onClick={() => setAuthMode("signup")}
                className="px-3 sm:px-4 py-1.5 bg-accent hover:bg-accent-hover text-accent-fg font-medium rounded-lg text-xs sm:text-sm transition-all"
              >
                Sign Up
              </button>
            </>
          )}
        </div>
      </nav>

      {/* Hero */}
      <div className="flex-1 flex flex-col items-center justify-center px-4 sm:px-6 py-8 md:py-16">
        {/* Auth modal overlay */}
        {authMode !== "none" && (
          <div className="w-full max-w-md mb-8">
            {authMode === "login" ? (
              <LoginForm onDone={() => setAuthMode("none")} onSwitch={() => setAuthMode("signup")} />
            ) : (
              <SignupForm onDone={() => setAuthMode("none")} onSwitch={() => setAuthMode("login")} />
            )}
          </div>
        )}

        {authMode === "none" && (
          <>
            {/* Logo + Tagline */}
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
                { icon: "\uD83D\uDD10", label: "Your data, encrypted" },
                { icon: "\uD83E\uDD16", label: "Personal AI agent" },
                { icon: "\uD83D\uDC65", label: "You choose who sees what" },
                { icon: "\uD83D\uDEE1\uFE0F", label: "Protected by AI security", href: "https://trymighty.ai" },
              ].map((f) => (
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
              ))}
            </div>

            {/* Navigation Links */}
            <div className="flex flex-col sm:flex-row gap-3 mb-8 md:mb-12">
              <Link
                href="/about"
                className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl bg-accent hover:bg-accent-hover text-accent-fg text-sm font-medium transition-all hover:shadow-lg hover:shadow-accent/20"
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
          </>
        )}
      </div>

      {/* Footer */}
      <footer className="py-4 sm:py-6 px-4 border-t border-card-border text-center space-y-1">
        <p className="text-xs text-muted-foreground">
          Built with love by <a href="https://github.com/masterfung" target="_blank" rel="noopener noreferrer" className="text-accent hover:text-accent-hover transition-colors">@masterfung</a> &middot; Powered by Gemini 3.1 Pro
        </p>
        <p className="text-xs text-muted-foreground">
          End-to-end encrypted &middot; <a href="https://trymighty.ai" target="_blank" rel="noopener noreferrer" className="text-red-400 hover:text-red-300 transition-colors">Protected by AI security</a>
        </p>
      </footer>
    </div>
  );
}

function LoginForm({ onDone, onSwitch }: { onDone: () => void; onSwitch: () => void }) {
  const { login } = useAuth();
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isPending, setIsPending] = useState(false);

  const handleSubmit = async () => {
    setError("");
    setIsPending(true);
    try {
      const user = await login(name, password);
      window.location.href = `/${user.id}`;
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setIsPending(false);
    }
  };

  return (
    <div className="bg-card border border-card-border rounded-2xl p-5 sm:p-6 shadow-xl shadow-black/20">
      <h2 className="text-lg sm:text-xl font-bold mb-1">Welcome Back</h2>
      <p className="text-xs sm:text-sm text-muted-foreground mb-5">
        Log in with your name, email, or handle.
      </p>

      {error && (
        <div className="text-danger text-sm mb-4 p-3 bg-danger-dim rounded-lg border border-danger/20">
          {error}
        </div>
      )}

      <div className="space-y-4 mb-5">
        <div>
          <label className="block text-sm text-muted-foreground mb-1.5 font-medium">Name, email, or @handle</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g., Amy Lee or amy@email.com"
            className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-accent/50 focus:border-accent/50"
            onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
          />
        </div>
        <div>
          <label className="block text-sm text-muted-foreground mb-1.5 font-medium">Password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Your password"
            className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-accent/50 focus:border-accent/50"
            onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
          />
        </div>
      </div>

      <div className="flex gap-3 mb-4">
        <button
          onClick={handleSubmit}
          disabled={!name.trim() || !password.trim() || isPending}
          className="flex-1 py-2.5 bg-accent hover:bg-accent-hover text-accent-fg font-semibold rounded-xl text-sm disabled:opacity-40 disabled:cursor-not-allowed transition-all hover:shadow-lg hover:shadow-accent/25"
        >
          {isPending ? (
            <span className="flex items-center justify-center gap-2">
              <Loader2 className="animate-spin" size={16} />
              Authenticating...
            </span>
          ) : "Log In"}
        </button>
        <button
          onClick={onDone}
          className="px-5 py-2.5 text-sm text-muted-foreground hover:text-foreground rounded-xl hover:bg-card-hover transition-colors"
        >
          Cancel
        </button>
      </div>

      <p className="text-center text-xs text-muted-foreground">
        Don&apos;t have an account?{" "}
        <button onClick={onSwitch} className="text-accent hover:text-accent-hover transition-colors">
          Sign up
        </button>
      </p>
    </div>
  );
}

function SignupForm({ onDone, onSwitch }: { onDone: () => void; onSwitch: () => void }) {
  const { signup } = useAuth();
  const queryClient = useQueryClient();
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [bio, setBio] = useState("");
  const [password, setPassword] = useState("");
  const [avatarPreview, setAvatarPreview] = useState<string | null>(null);
  const [error, setError] = useState("");
  const passwordError = password.length > 0 ? validatePasswordComplexity(password) : null;
  const nameError = displayName.length > 0 ? validateName(displayName) : null;

  const handleAvatarChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 500_000) { setError("Image must be under 500KB"); return; }
    if (!file.type.startsWith("image/")) { setError("File must be an image"); return; }
    const reader = new FileReader();
    reader.onload = () => { setAvatarPreview(reader.result as string); setError(""); };
    reader.readAsDataURL(file);
  };

  const mutation = useMutation({
    mutationFn: () =>
      signup({ display_name: displayName.trim(), bio, password, email: email || undefined, avatar_url: avatarPreview || undefined }),
    onSuccess: (newUser) => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      window.location.href = `/${newUser.id}/onboard`;
    },
    onError: (err: Error) => setError(err.message),
  });

  const isValid = displayName.trim() && !nameError && !passwordError && password.length >= 16;

  return (
    <div className="bg-card border border-card-border rounded-2xl p-5 sm:p-6 shadow-xl shadow-black/20">
      <h2 className="text-lg sm:text-xl font-bold mb-1">Get Started</h2>
      <p className="text-xs sm:text-sm text-muted-foreground mb-5">
        Your own AI assistant and private memories. Private by default.
      </p>

      {error && (
        <div className="text-danger text-sm mb-4 p-3 bg-danger-dim rounded-lg border border-danger/20">
          {error}
        </div>
      )}

      <div className="space-y-4 mb-5">
        {/* Avatar */}
        <div className="flex items-center gap-4">
          <label htmlFor="avatar-upload" className="cursor-pointer group relative">
            <div className="w-14 h-14 sm:w-16 sm:h-16 rounded-full bg-background border-2 border-dashed border-card-border group-hover:border-accent/50 transition-colors flex items-center justify-center overflow-hidden">
              {avatarPreview ? (
                <img src={avatarPreview} alt="Avatar" className="w-full h-full object-cover" />
              ) : (
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-muted-foreground group-hover:text-accent transition-colors">
                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" />
                </svg>
              )}
            </div>
            <input id="avatar-upload" type="file" accept="image/*" className="hidden" onChange={handleAvatarChange} />
          </label>
          <div>
            <p className="text-sm font-medium">Profile photo</p>
            <p className="text-xs text-muted-foreground">
              <label htmlFor="avatar-upload" className="cursor-pointer text-accent hover:text-accent-hover transition-colors">Upload photo</label> &middot; max 500KB
            </p>
          </div>
        </div>

        {/* Name */}
        <div>
          <label className="block text-sm text-muted-foreground mb-1.5 font-medium">Full Name</label>
          <input
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="e.g., Amy Lee"
            className={`w-full bg-background border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-accent/50 ${
              nameError ? "border-danger/50" : "border-card-border focus:border-accent/50"
            }`}
          />
          {nameError && <p className="text-xs text-danger mt-1">{nameError}</p>}
        </div>

        {/* Email */}
        <div>
          <label className="block text-sm text-muted-foreground mb-1.5 font-medium">Email <span className="text-muted-foreground">(optional)</span></label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-accent/50 focus:border-accent/50"
          />
          <p className="text-xs text-muted-foreground mt-1">For account recovery. Never shared.</p>
        </div>

        {/* Password */}
        <div>
          <label className="block text-sm text-muted-foreground mb-1.5 font-medium">Password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Min 16 chars, mixed case + digit + special"
            className={`w-full bg-background border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-accent/50 ${
              passwordError ? "border-danger/50" : "border-card-border focus:border-accent/50"
            }`}
          />
          {passwordError ? (
            <p className="text-xs text-danger mt-1">{passwordError}</p>
          ) : password.length > 0 ? (
            <p className="text-xs text-green-400 mt-1">Password meets complexity requirements</p>
          ) : (
            <p className="text-xs text-muted-foreground mt-1">Protects your private memories with end-to-end encryption</p>
          )}
        </div>

        {/* Bio */}
        <div>
          <label className="block text-sm text-muted-foreground mb-1.5 font-medium">About you <span className="text-muted-foreground">(optional)</span></label>
          <input
            type="text"
            value={bio}
            onChange={(e) => setBio(e.target.value)}
            placeholder="A brief intro so your AI assistant can help you better..."
            className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-accent/50 focus:border-accent/50"
          />
        </div>
      </div>

      <div className="flex gap-3 mb-4">
        <button
          onClick={() => mutation.mutate()}
          disabled={!isValid || mutation.isPending}
          className="flex-1 py-2.5 bg-accent hover:bg-accent-hover text-accent-fg font-semibold rounded-xl text-sm disabled:opacity-40 disabled:cursor-not-allowed transition-all hover:shadow-lg hover:shadow-accent/25"
        >
          {mutation.isPending ? (
            <span className="flex items-center justify-center gap-2">
              <Loader2 className="animate-spin" size={16} />
              Creating your account...
            </span>
          ) : "Create Account"}
        </button>
        <button
          onClick={onDone}
          className="px-5 py-2.5 text-sm text-muted-foreground hover:text-foreground rounded-xl hover:bg-card-hover transition-colors"
        >
          Cancel
        </button>
      </div>

      <p className="text-center text-xs text-muted-foreground">
        Already have an account?{" "}
        <button onClick={onSwitch} className="text-accent hover:text-accent-hover transition-colors">
          Log in
        </button>
      </p>
    </div>
  );
}
