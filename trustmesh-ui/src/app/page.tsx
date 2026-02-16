"use client";

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type User, setPodUrl } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { User as UserIcon, Building2, Landmark, Loader2 } from "lucide-react";

const DEMO_PASSWORD = "TrustMesh-demo-2026";

const USER_COLORS: Record<string, string> = {
  peter:       "from-blue-500 to-cyan-400",
  molly:       "from-amber-500 to-yellow-400",
  jane:        "from-pink-500 to-rose-400",
  bill:        "from-emerald-500 to-green-400",
  kyle:        "from-orange-500 to-amber-400",
  grandmarose: "from-purple-500 to-violet-400",
  linda:       "from-teal-500 to-cyan-400",
  amy:         "from-fuchsia-500 to-pink-400",
  marcus:      "from-slate-500 to-zinc-400",
  dorothy:     "from-indigo-500 to-blue-400",
  dr_lee:      "from-sky-500 to-blue-400",
  nurse_davis: "from-red-500 to-rose-400",
  emt_johnson: "from-lime-500 to-green-400",
};

const ENTITY_CONFIG: Record<string, { label: string; icon: React.ReactNode; accent: string }> = {
  person:       { label: "People",        icon: <UserIcon size={16} />,  accent: "text-blue-400" },
  organization: { label: "Organizations", icon: <Building2 size={16} />, accent: "text-amber-400" },
  government:   { label: "Government",    icon: <Landmark size={16} />,  accent: "text-emerald-400" },
};

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

  // Reset pod URL to default on the home/login page so we always hit the main pod.
  // Users who previously used PodSwitcher may have localStorage pointing at a dead multi-pod port.
  useEffect(() => {
    if (typeof window !== "undefined") {
      localStorage.removeItem("trustmesh_pod_url");
    }
  }, []);

  const { data: users, isLoading } = useQuery({
    queryKey: ["users"],
    queryFn: api.listUsers,
  });
  const [authMode, setAuthMode] = useState<"none" | "login" | "signup">("none");

  if (authLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-muted-foreground animate-pulse">Loading...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col">
      {/* Top Nav */}
      <nav className="flex items-center justify-end gap-3 px-6 py-3">
        <Link
          href="/about"
          className="text-xs text-muted-foreground hover:text-foreground transition-colors px-3 py-1.5 rounded-lg hover:bg-card"
        >
          Protocol Docs
        </Link>
        <a
          href="http://localhost:8100"
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-muted-foreground hover:text-foreground transition-colors px-3 py-1.5 rounded-lg hover:bg-card"
        >
          Agent Registry
        </a>
      </nav>

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
          <p className="text-lg md:text-xl text-foreground max-w-2xl mx-auto leading-relaxed font-medium">
            The trust layer for personal AI agents.
          </p>
          <p className="text-base text-muted-foreground max-w-xl mx-auto leading-relaxed mt-3">
            Everyone gets an encrypted vault and an AI agent powered by Opus 4.6.
            Agents collaborate across trust boundaries — sharing what&apos;s needed,
            protecting everything else. One command to start. Zero configuration.
          </p>
        </div>

        {/* Feature Pills */}
        <div className="flex flex-wrap justify-center gap-3 mb-12">
          {[
            { icon: "🔐", label: "Your data, encrypted" },
            { icon: "🤖", label: "Personal AI agent" },
            { icon: "👥", label: "You choose who sees what" },
            { icon: "🛡️", label: "Citadel Security", href: "https://trymighty.ai" },
          ].map((f) => (
            "href" in f && f.href ? (
              <a
                key={f.label}
                href={f.href}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2 px-4 py-2 rounded-full bg-card border border-card-border text-sm text-muted-foreground hover:border-red-500/40 hover:text-red-400 transition-colors"
              >
                <span>{f.icon}</span>
                <span>{f.label}</span>
              </a>
            ) : (
              <div
                key={f.label}
                className="flex items-center gap-2 px-4 py-2 rounded-full bg-card border border-card-border text-sm text-muted-foreground"
              >
                <span>{f.icon}</span>
                <span>{f.label}</span>
              </div>
            )
          ))}
        </div>

        {/* Navigation Links */}
        <div className="flex gap-3 mb-12">
          <Link
            href="/about"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-accent hover:bg-accent-hover text-accent-fg text-sm font-medium transition-all hover:shadow-lg hover:shadow-accent/20"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>
            </svg>
            Why TrustMesh?
          </Link>
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
          {isLoading ? (
            <div className="flex justify-center">
              <div className="text-muted-foreground animate-pulse">Loading...</div>
            </div>
          ) : (users || []).filter(u => u.is_demo).length <= 1 ? (
            <SinglePodHome users={users || []} />
          ) : (
            <>
              <div className="text-center mb-6">
                <p className="text-sm text-muted-foreground">
                  Or explore the demo — pick an entity to see their perspective:
                </p>
              </div>
              <DemoUserGrid users={users || []} />
            </>
          )}
        </div>

      </div>

      {/* Footer */}
      <footer className="py-6 px-4 border-t border-card-border text-center space-y-1">
        <p className="text-xs text-muted-foreground">
          Built with love by <a href="https://github.com/masterfung" target="_blank" rel="noopener noreferrer" className="text-accent hover:text-accent-hover transition-colors">@masterfung</a> &middot; Powered by Claude Opus 4.6
        </p>
        <p className="text-xs text-muted-foreground">
          AES-256-GCM Encryption &middot; <a href="https://trymighty.ai" target="_blank" rel="noopener noreferrer" className="text-red-400 hover:text-red-300 transition-colors">Citadel Security</a>
        </p>
      </footer>
    </div>
  );
}

const QUICK_PODS = [
  { port: 8001, name: "Molly Johnson",       type: "person",       username: "molly" },
  { port: 8002, name: "Peter Johnson",       type: "person",       username: "peter" },
  { port: 8003, name: "Jane Johnson",        type: "person",       username: "jane" },
  { port: 8004, name: "Grandma Rose",        type: "person",       username: "grandmarose" },
  { port: 8005, name: "Dr. Sarah Lee",       type: "person",       username: "dr_lee" },
  { port: 8006, name: "Kyle Rivera",         type: "person",       username: "kyle" },
  { port: 8007, name: "Amy Torres",          type: "person",       username: "amy" },
  { port: 8008, name: "Dorothy Park",        type: "person",       username: "dorothy" },
  { port: 8009, name: "Nurse Rachel Davis",  type: "person",       username: "nurse_davis" },
  { port: 8010, name: "EMT Mike Johnson",    type: "person",       username: "emt_johnson" },
  { port: 8011, name: "SparkleClean",        type: "organization", username: "sparkleclean" },
  { port: 8012, name: "Riverside Hospital",  type: "organization", username: "riverside_hospital" },
  { port: 8013, name: "AceTutor SAT Prep",   type: "organization", username: "acetutor" },
  { port: 8014, name: "City of Riverside",   type: "government",   username: "riverside_gov" },
  { port: 8015, name: "HandyPro",            type: "organization", username: "handypro" },
  { port: 8016, name: "Riverside Ambulance", type: "organization", username: "riverside_ambulance" },
];

function SinglePodHome({ users }: { users: User[] }) {
  const { loginAsDemo } = useAuth();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [multiPodAvailable, setMultiPodAvailable] = useState<boolean | null>(null);

  const demoUser = users.find((u) => u.is_demo);

  // Check if multi-pod federation is running
  useState(() => {
    fetch("http://localhost:8001/health", { signal: AbortSignal.timeout(2000) })
      .then((r) => setMultiPodAvailable(r.ok))
      .catch(() => setMultiPodAvailable(false));
  });

  const handleLogin = async (user: User) => {
    setLoading(true);
    setError("");
    try {
      const loggedIn = await loginAsDemo(user.username, DEMO_PASSWORD);
      // Full page load avoids race between setUser() and layout redirect useEffect
      window.location.href = `/${loggedIn.id}`;
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Login failed");
      setLoading(false);
    }
  };

  const switchToPod = (port: number) => {
    setPodUrl(`http://localhost:${port}`);
    window.location.reload();
  };

  // No demo user — show pod picker if multi-pod is available
  if (!demoUser) {
    if (multiPodAvailable) {
      return (
        <div className="space-y-6">
          <div className="text-center">
            <p className="text-sm text-muted-foreground mb-1">
              Multi-pod federation detected. Pick a pod to explore:
            </p>
          </div>

          {(["person", "organization", "government"] as const).map((type) => {
            const pods = QUICK_PODS.filter((p) => p.type === type);
            if (pods.length === 0) return null;
            const config = ENTITY_CONFIG[type];
            return (
              <div key={type}>
                <div className="flex items-center gap-2 mb-2">
                  <span className={config.accent}>{config.icon}</span>
                  <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">{config.label}</h3>
                </div>
                <div className={`grid gap-2 ${
                  type === "person" ? "grid-cols-2 sm:grid-cols-3 lg:grid-cols-5" : "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3"
                }`}>
                  {pods.map((pod) => (
                    <button
                      key={pod.port}
                      onClick={() => switchToPod(pod.port)}
                      className="group p-3 rounded-xl bg-card border border-card-border hover:border-accent/50 transition-all hover:bg-card-hover text-left"
                    >
                      <div className="flex items-center gap-2">
                        <div className={`w-8 h-8 rounded-full bg-gradient-to-br ${USER_COLORS[pod.username] || "from-zinc-600 to-zinc-400"} flex items-center justify-center text-white font-bold text-sm`}>
                          {pod.name[0]}
                        </div>
                        <div className="min-w-0">
                          <p className="text-sm font-semibold truncate">{pod.name}</p>
                          <p className="text-[10px] text-muted-foreground">:{pod.port}</p>
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            );
          })}

          <div className="text-center">
            <p className="text-xs text-muted-foreground">
              Or browse the{" "}
              <a href="http://localhost:8100" target="_blank" rel="noopener noreferrer" className="text-accent hover:text-accent-hover transition-colors">
                Agent Registry
              </a>
            </p>
          </div>
        </div>
      );
    }

    return (
      <div className="text-center py-8 text-muted-foreground text-sm">
        No demo users available. Start the backend with <code className="bg-card px-1.5 py-0.5 rounded text-xs">./dev.sh start</code> or <code className="bg-card px-1.5 py-0.5 rounded text-xs">./multi-pod.sh demo</code>
      </div>
    );
  }

  // Single demo user — show them prominently with option to switch
  return (
    <div className="space-y-6">
      <div className="text-center">
        <p className="text-sm text-muted-foreground">
          This pod belongs to:
        </p>
      </div>

      {error && (
        <div className="text-danger text-sm p-3 bg-danger-dim rounded-lg border border-danger/20 text-center">
          {error}
        </div>
      )}

      <button
        onClick={() => handleLogin(demoUser)}
        disabled={loading}
        className="w-full max-w-md mx-auto flex items-center gap-4 p-5 rounded-2xl bg-card border border-card-border hover:border-accent/50 transition-all hover:bg-card-hover text-left disabled:opacity-60 group"
      >
        <div
          className={`w-14 h-14 rounded-full bg-gradient-to-br ${USER_COLORS[demoUser.username] || "from-zinc-600 to-zinc-400"} flex items-center justify-center text-white font-bold text-xl transition-transform group-hover:scale-110 ring-2 ring-transparent group-hover:ring-accent/30`}
        >
          {loading ? <Loader2 className="animate-spin" size={24} /> : demoUser.display_name[0]}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h2 className="text-foreground font-bold text-lg">{demoUser.display_name}</h2>
            <span className={`shrink-0 text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded ${
              demoUser.user_type === "government" ? "text-emerald-400 bg-emerald-500/10" :
              demoUser.user_type === "organization" ? "text-amber-400 bg-amber-500/10" :
              "text-blue-400 bg-blue-500/10"
            }`}>
              {demoUser.user_type === "government" ? "Gov" : demoUser.user_type === "organization" ? "Org" : "Person"}
            </span>
          </div>
          <p className="text-sm text-muted-foreground mt-1 line-clamp-2">{demoUser.bio}</p>
        </div>
      </button>

      {multiPodAvailable && (
        <div className="text-center">
          <p className="text-xs text-muted-foreground mb-3">Or switch to another pod:</p>
          <div className="flex flex-wrap justify-center gap-1.5">
            {QUICK_PODS.filter(p => p.username !== demoUser.username).slice(0, 8).map((pod) => (
              <button
                key={pod.port}
                onClick={() => switchToPod(pod.port)}
                className="px-2.5 py-1 rounded-lg bg-card border border-card-border hover:border-accent/50 transition-all hover:bg-card-hover text-xs text-muted-foreground hover:text-foreground"
              >
                {pod.name.split(" ")[0]}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="text-center">
        <p className="text-xs text-muted-foreground">
          Browse the{" "}
          <a href="http://localhost:8100" target="_blank" rel="noopener noreferrer" className="text-accent hover:text-accent-hover transition-colors">
            Agent Registry
          </a>
          {" "}to discover all agents across the network
        </p>
      </div>
    </div>
  );
}

function DemoUserGrid({ users }: { users: User[] }) {
  const { loginAsDemo } = useAuth();
  const [loadingUser, setLoadingUser] = useState<string | null>(null);
  const [error, setError] = useState("");

  const demoUsers = users.filter((u) => u.is_demo);

  // Group by entity type, preserving order
  const groups = (["person", "organization", "government"] as const).map((type) => ({
    type,
    config: ENTITY_CONFIG[type],
    users: demoUsers.filter((u) => u.user_type === type),
  })).filter((g) => g.users.length > 0);

  const handleDemoLogin = async (user: User) => {
    setLoadingUser(user.id);
    setError("");
    try {
      const loggedIn = await loginAsDemo(user.username, DEMO_PASSWORD);
      // Full page load avoids race between setUser() and layout redirect useEffect
      window.location.href = `/${loggedIn.id}`;
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Demo login failed");
      setLoadingUser(null);
    }
  };

  return (
    <div>
      {error && (
        <div className="text-danger text-sm mb-4 p-3 bg-danger-dim rounded-lg border border-danger/20 text-center">
          {error}
        </div>
      )}

      {groups.map(({ type, config, users: groupUsers }) => (
        <div key={type} className="mb-6">
          <div className="flex items-center gap-2 mb-3">
            <span className={config.accent}>{config.icon}</span>
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">{config.label}</h3>
          </div>
          <div className={`grid gap-3 ${
            type === "person"
              ? "grid-cols-2 sm:grid-cols-3 lg:grid-cols-5"
              : "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3"
          }`}>
            {groupUsers.map((user: User) => type === "person" ? (
              <button
                key={user.id}
                onClick={() => handleDemoLogin(user)}
                disabled={loadingUser !== null}
                className="group relative p-4 rounded-xl bg-card border border-card-border hover:border-accent/50 transition-all hover:bg-card-hover text-left disabled:opacity-60"
              >
                <div
                  className={`w-12 h-12 rounded-full bg-gradient-to-br ${USER_COLORS[user.username] || "from-zinc-600 to-zinc-400"} flex items-center justify-center text-white font-bold text-lg mb-3 transition-transform group-hover:scale-110 ring-2 ring-transparent group-hover:ring-accent/30`}
                >
                  {loadingUser === user.id ? <Loader2 className="animate-spin" size={20} /> : user.display_name[0]}
                </div>
                <h2 className="text-foreground font-semibold text-sm">{user.display_name}</h2>
                <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{user.bio}</p>
              </button>
            ) : (
              <button
                key={user.id}
                onClick={() => handleDemoLogin(user)}
                disabled={loadingUser !== null}
                className="group relative flex items-start gap-3 p-4 rounded-xl bg-card border border-card-border hover:border-accent/30 transition-all hover:bg-card-hover text-left disabled:opacity-60"
              >
                <div className={`w-10 h-10 rounded-lg bg-card-hover border border-card-border flex items-center justify-center shrink-0 transition-transform group-hover:scale-110 ${config.accent}`}>
                  {loadingUser === user.id ? <Loader2 className="animate-spin" size={18} /> : config.icon}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <h2 className="text-foreground font-semibold text-sm truncate">{user.display_name}</h2>
                    <span className={`shrink-0 text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded ${
                      type === "government" ? "text-emerald-400 bg-emerald-500/10" : "text-amber-400 bg-amber-500/10"
                    }`}>
                      {type === "government" ? "Gov" : "Org"}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{user.bio}</p>
                </div>
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function LoginForm({ onDone, onSwitch }: { onDone: () => void; onSwitch: () => void }) {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isPending, setIsPending] = useState(false);

  const handleSubmit = async () => {
    setError("");
    setIsPending(true);
    try {
      const user = await login(username, password);
      // Full page load avoids race between setUser() and layout redirect useEffect
      window.location.href = `/${user.id}`;
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setIsPending(false);
    }
  };

  return (
    <div className="bg-card border border-card-border rounded-2xl p-6 shadow-xl shadow-black/20">
      <h2 className="text-xl font-bold mb-1">Welcome Back</h2>
      <p className="text-sm text-muted-foreground mb-5">
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
            className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted-foregroundfocus:outline-none focus:ring-2 focus:ring-accent/50 focus:border-accent/50"
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
            className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted-foregroundfocus:outline-none focus:ring-2 focus:ring-accent/50 focus:border-accent/50"
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
      <p className="text-sm text-muted-foreground mb-5">
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
            className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted-foregroundfocus:outline-none focus:ring-2 focus:ring-accent/50 focus:border-accent/50"
          />
        </div>
        <div>
          <label className="block text-sm text-muted-foreground mb-1.5 font-medium">Display Name</label>
          <input
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="e.g., Alice Chen"
            className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted-foregroundfocus:outline-none focus:ring-2 focus:ring-accent/50 focus:border-accent/50"
          />
        </div>
        <div>
          <label className="block text-sm text-muted-foreground mb-1.5 font-medium">Password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Min 16 chars, mixed case + digit + special"
            className={`w-full bg-background border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted-foregroundfocus:outline-none focus:ring-2 focus:ring-accent/50 ${
              passwordError ? "border-danger/50" : "border-card-border focus:border-accent/50"
            }`}
          />
          {passwordError ? (
            <p className="text-xs text-danger mt-1">{passwordError}</p>
          ) : password.length > 0 ? (
            <p className="text-xs text-green-400 mt-1">Password meets complexity requirements</p>
          ) : (
            <p className="text-xs text-muted-foreground mt-1">Argon2id derives your AES-256 vault key</p>
          )}
        </div>
        <div>
          <label className="block text-sm text-muted-foreground mb-1.5 font-medium">Bio <span className="text-muted-foreground">(optional)</span></label>
          <input
            type="text"
            value={bio}
            onChange={(e) => setBio(e.target.value)}
            placeholder="Tell others about yourself..."
            className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted-foregroundfocus:outline-none focus:ring-2 focus:ring-accent/50 focus:border-accent/50"
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

      <p className="text-center text-xs text-muted-foreground">
        Already have an account?{" "}
        <button onClick={onSwitch} className="text-accent hover:text-accent-hover transition-colors">
          Log in
        </button>
      </p>
    </div>
  );
}
