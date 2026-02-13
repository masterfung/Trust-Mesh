"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type User } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import Link from "next/link";
import { useRouter } from "next/navigation";

const DEMO_PASSWORD = "TrustMesh-demo-2026";

const USER_COLORS: Record<string, string> = {
  peter: "from-blue-500 to-cyan-400",
  molly: "from-amber-500 to-yellow-400",
  jane: "from-pink-500 to-rose-400",
  bill: "from-emerald-500 to-green-400",
  kyle: "from-orange-500 to-amber-400",
};

const SERVICE_ICON = (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="2" y="7" width="20" height="14" rx="2" ry="2"/><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/>
  </svg>
);

const PERSON_ICON = (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
  </svg>
);

function validatePasswordComplexity(pw: string): string | null {
  if (pw.length < 16) return "Password must be at least 16 characters";
  if (!/[A-Z]/.test(pw)) return "Must contain an uppercase letter";
  if (!/[a-z]/.test(pw)) return "Must contain a lowercase letter";
  if (!/[0-9]/.test(pw)) return "Must contain a digit";
  if (!/[^A-Za-z0-9]/.test(pw)) return "Must contain a special character (!@#$%^&* etc.)";
  return null;
}

export default function Home() {
  const { user: authUser, isLoading: authLoading, logout } = useAuth();
  const router = useRouter();
  const { data: users, isLoading } = useQuery({
    queryKey: ["users"],
    queryFn: api.listUsers,
  });
  const [authMode, setAuthMode] = useState<"none" | "login" | "signup">("none");

  if (authLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-muted animate-pulse">Loading...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col">
      {/* Hero */}
      <div className="flex-1 flex flex-col items-center justify-center p-6 md:p-12">
        {/* Logo + Tagline */}
        <div className="text-center mb-12">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-accent/10 border border-accent/20 text-accent text-xs font-medium mb-6">
            <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
            Powered by Claude Opus 4.6
          </div>
          <h1 className="text-5xl md:text-6xl font-bold tracking-tight mb-4">
            <span className="text-gradient">TrustMesh</span>
          </h1>
          <p className="text-lg md:text-xl text-muted-foreground max-w-2xl mx-auto leading-relaxed">
            Your personal AI agent holds your knowledge and shares it with the right
            people — powered by trust networks and encrypted vaults.
          </p>
        </div>

        {/* Feature Pills */}
        <div className="flex flex-wrap justify-center gap-3 mb-12">
          {[
            { icon: "🔐", label: "AES-256 Encrypted" },
            { icon: "🤖", label: "AI Agent Per User" },
            { icon: "🛡️", label: "Trust-Tiered Access" },
            { icon: "🔍", label: "Citadel Security" },
          ].map((f) => (
            <div
              key={f.label}
              className="flex items-center gap-2 px-4 py-2 rounded-full bg-card border border-card-border text-sm text-muted-foreground"
            >
              <span>{f.icon}</span>
              <span>{f.label}</span>
            </div>
          ))}
        </div>

        {/* Auth Forms */}
        <div className="w-full max-w-lg mb-12">
          {authUser ? (
            <div className="flex gap-3">
              <button
                onClick={() => router.push(`/${authUser.id}`)}
                className="flex-1 py-3.5 bg-accent hover:bg-accent-hover text-accent-fg font-semibold rounded-xl text-base transition-all hover:shadow-lg hover:shadow-accent/25"
              >
                Continue as {authUser.display_name}
              </button>
              <button
                onClick={() => logout()}
                className="px-5 py-3.5 bg-card border border-card-border hover:border-accent/50 text-muted-foreground hover:text-foreground font-medium rounded-xl text-sm transition-all hover:bg-card-hover"
              >
                Log Out
              </button>
            </div>
          ) : authMode === "login" ? (
            <LoginForm onDone={() => setAuthMode("none")} onSwitch={() => setAuthMode("signup")} />
          ) : authMode === "signup" ? (
            <SignupForm onDone={() => setAuthMode("none")} onSwitch={() => setAuthMode("login")} />
          ) : (
            <div className="flex gap-3">
              <button
                onClick={() => setAuthMode("login")}
                className="flex-1 py-3.5 bg-accent hover:bg-accent-hover text-accent-fg font-semibold rounded-xl text-base transition-all hover:shadow-lg hover:shadow-accent/25"
              >
                Log In
              </button>
              <button
                onClick={() => setAuthMode("signup")}
                className="flex-1 py-3.5 bg-card border border-card-border hover:border-accent/50 text-foreground font-semibold rounded-xl text-base transition-all hover:bg-card-hover"
              >
                Sign Up
              </button>
            </div>
          )}
        </div>

        {/* Demo Users */}
        <div className="w-full max-w-4xl">
          <div className="text-center mb-6">
            <p className="text-sm text-muted">
              Or explore the demo — pick a person or service to see their perspective:
            </p>
          </div>

          {isLoading ? (
            <div className="flex justify-center">
              <div className="text-muted animate-pulse">Loading...</div>
            </div>
          ) : (
            <DemoUserGrid users={users || []} />
          )}
        </div>

        {/* Graph Link */}
        <div className="mt-10">
          <Link
            href="/graph"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-card border border-card-border text-sm text-muted-foreground hover:text-foreground hover:border-accent/50 transition-all"
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
      <footer className="py-6 px-4 border-t border-card-border text-center">
        <p className="text-xs text-muted">
          Built with Claude Opus 4.6 for the Claude Code Hackathon &middot; AES-256-GCM Encryption &middot; Citadel Security Scanning
        </p>
      </footer>
    </div>
  );
}

function DemoUserGrid({ users }: { users: User[] }) {
  const { loginAsDemo } = useAuth();
  const router = useRouter();
  const [loadingUser, setLoadingUser] = useState<string | null>(null);
  const [error, setError] = useState("");

  const demoUsers = users.filter((u) => u.is_demo);
  const people = demoUsers.filter((u) => u.user_type !== "service");
  const services = demoUsers.filter((u) => u.user_type === "service");

  const handleDemoLogin = async (user: User) => {
    setLoadingUser(user.id);
    setError("");
    try {
      const loggedIn = await loginAsDemo(user.username, DEMO_PASSWORD);
      router.push(`/${loggedIn.id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Demo login failed");
      setLoadingUser(null);
    }
  };

  const Spinner = () => (
    <svg className="animate-spin w-5 h-5" viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
    </svg>
  );

  return (
    <div>
      {error && (
        <div className="text-danger text-sm mb-4 p-3 bg-danger-dim rounded-lg border border-danger/20 text-center">
          {error}
        </div>
      )}

      {/* People */}
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-3">
          <span className="text-muted-foreground">{PERSON_ICON}</span>
          <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">People</h3>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          {people.map((user: User) => (
            <button
              key={user.id}
              onClick={() => handleDemoLogin(user)}
              disabled={loadingUser !== null}
              className="group relative p-4 rounded-xl bg-card border border-card-border hover:border-accent/50 transition-all hover:bg-card-hover text-left disabled:opacity-60"
            >
              <div
                className={`w-12 h-12 rounded-full bg-gradient-to-br ${USER_COLORS[user.username] || "from-zinc-600 to-zinc-400"} flex items-center justify-center text-white font-bold text-lg mb-3 transition-transform group-hover:scale-110 ring-2 ring-transparent group-hover:ring-accent/30`}
              >
                {loadingUser === user.id ? <Spinner /> : user.display_name[0]}
              </div>
              <h2 className="text-foreground font-semibold text-sm">{user.display_name}</h2>
              <p className="text-xs text-muted mt-1 line-clamp-2">{user.bio}</p>
            </button>
          ))}
        </div>
      </div>

      {/* Services */}
      {services.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <span className="text-accent">{SERVICE_ICON}</span>
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Service Providers</h3>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {services.map((user: User) => (
              <button
                key={user.id}
                onClick={() => handleDemoLogin(user)}
                disabled={loadingUser !== null}
                className="group relative flex items-start gap-3 p-4 rounded-xl bg-card border border-accent/15 hover:border-accent/40 transition-all hover:bg-card-hover text-left disabled:opacity-60"
              >
                <div className="w-10 h-10 rounded-lg bg-accent/10 border border-accent/20 flex items-center justify-center text-accent shrink-0 transition-transform group-hover:scale-110">
                  {loadingUser === user.id ? <Spinner /> : SERVICE_ICON}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <h2 className="text-foreground font-semibold text-sm truncate">{user.display_name}</h2>
                    <span className="shrink-0 text-[9px] font-bold uppercase tracking-wider text-accent bg-accent/10 px-1.5 py-0.5 rounded">
                      Service
                    </span>
                  </div>
                  <p className="text-xs text-muted mt-1 line-clamp-2">{user.bio}</p>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function LoginForm({ onDone, onSwitch }: { onDone: () => void; onSwitch: () => void }) {
  const { login } = useAuth();
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isPending, setIsPending] = useState(false);

  const handleSubmit = async () => {
    setError("");
    setIsPending(true);
    try {
      const user = await login(username, password);
      router.push(`/${user.id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setIsPending(false);
    }
  };

  return (
    <div className="bg-card border border-card-border rounded-2xl p-6 shadow-xl shadow-black/20">
      <h2 className="text-xl font-bold mb-1">Welcome Back</h2>
      <p className="text-sm text-muted mb-5">
        Log in to access your AI agent and encrypted vault.
      </p>

      {error && (
        <div className="text-danger text-sm mb-4 p-3 bg-danger-dim rounded-lg border border-danger/20">
          {error}
        </div>
      )}

      <div className="space-y-4 mb-5">
        <div>
          <label className="block text-sm text-muted-foreground mb-1.5 font-medium">Username</label>
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, ""))}
            placeholder="e.g., peter"
            className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent/50 focus:border-accent/50"
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
            className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent/50 focus:border-accent/50"
            onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
          />
        </div>
      </div>

      <div className="flex gap-3 mb-4">
        <button
          onClick={handleSubmit}
          disabled={!username.trim() || !password.trim() || isPending}
          className="flex-1 py-2.5 bg-accent hover:bg-accent-hover text-accent-fg font-semibold rounded-xl text-sm disabled:opacity-40 disabled:cursor-not-allowed transition-all hover:shadow-lg hover:shadow-accent/25"
        >
          {isPending ? (
            <span className="flex items-center justify-center gap-2">
              <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
              </svg>
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

      <p className="text-center text-xs text-muted">
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
  const router = useRouter();
  const queryClient = useQueryClient();
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [bio, setBio] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const passwordError = password.length > 0 ? validatePasswordComplexity(password) : null;

  const mutation = useMutation({
    mutationFn: () =>
      signup({ username, display_name: displayName, bio, password }),
    onSuccess: (newUser) => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      // Use window.location to avoid race with Home's auth redirect useEffect
      window.location.href = `/${newUser.id}/onboard`;
    },
    onError: (err: Error) => setError(err.message),
  });

  const isValid = username.trim() && displayName.trim() && !passwordError && password.length >= 16;

  return (
    <div className="bg-card border border-card-border rounded-2xl p-6 shadow-xl shadow-black/20">
      <h2 className="text-xl font-bold mb-1">Create Your Account</h2>
      <p className="text-sm text-muted mb-5">
        A personal AI agent and encrypted vault will be created for you.
      </p>

      {error && (
        <div className="text-danger text-sm mb-4 p-3 bg-danger-dim rounded-lg border border-danger/20">
          {error}
        </div>
      )}

      <div className="space-y-4 mb-5">
        <div>
          <label className="block text-sm text-muted-foreground mb-1.5 font-medium">Username</label>
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, ""))}
            placeholder="e.g., alice"
            className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent/50 focus:border-accent/50"
          />
        </div>
        <div>
          <label className="block text-sm text-muted-foreground mb-1.5 font-medium">Display Name</label>
          <input
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="e.g., Alice Chen"
            className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent/50 focus:border-accent/50"
          />
        </div>
        <div>
          <label className="block text-sm text-muted-foreground mb-1.5 font-medium">Password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Min 16 chars, mixed case + digit + special"
            className={`w-full bg-background border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent/50 ${
              passwordError ? "border-danger/50" : "border-card-border focus:border-accent/50"
            }`}
          />
          {passwordError ? (
            <p className="text-xs text-danger mt-1">{passwordError}</p>
          ) : password.length > 0 ? (
            <p className="text-xs text-green-400 mt-1">Password meets complexity requirements</p>
          ) : (
            <p className="text-xs text-muted mt-1">Argon2id derives your AES-256 vault key</p>
          )}
        </div>
        <div>
          <label className="block text-sm text-muted-foreground mb-1.5 font-medium">Bio <span className="text-muted">(optional)</span></label>
          <input
            type="text"
            value={bio}
            onChange={(e) => setBio(e.target.value)}
            placeholder="Tell others about yourself..."
            className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent/50 focus:border-accent/50"
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
              <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
              </svg>
              Creating...
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

      <p className="text-center text-xs text-muted">
        Already have an account?{" "}
        <button onClick={onSwitch} className="text-accent hover:text-accent-hover transition-colors">
          Log in
        </button>
      </p>
    </div>
  );
}
