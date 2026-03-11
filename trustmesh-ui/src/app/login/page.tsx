"use client";

import { useState, useRef, useEffect } from "react";
import { useAuth } from "@/lib/auth";
import Link from "next/link";
import { Loader2, ChevronDown, Check } from "lucide-react";
import { setPodUrl, getPodUrl } from "@/lib/api";

const DEMO_PODS = [
  { label: "Molly Johnson", sublabel: ":9001", url: "http://localhost:9001" },
  { label: "Peter Johnson", sublabel: ":9002", url: "http://localhost:9002" },
  { label: "Jane Johnson", sublabel: ":9003", url: "http://localhost:9003" },
  { label: "Grandma Rose", sublabel: ":9004", url: "http://localhost:9004" },
  { label: "Dr. Sarah Lee", sublabel: ":9005", url: "http://localhost:9005" },
  { label: "Kyle Rivera", sublabel: ":9006", url: "http://localhost:9006" },
  { label: "Amy Torres", sublabel: ":9007", url: "http://localhost:9007" },
  { label: "Dorothy Park", sublabel: ":9008", url: "http://localhost:9008" },
  { label: "Nurse Davis", sublabel: ":9009", url: "http://localhost:9009" },
  { label: "EMT Mike", sublabel: ":9010", url: "http://localhost:9010" },
  { label: "SparkleClean", sublabel: ":9011", url: "http://localhost:9011" },
  { label: "Riverside Hospital", sublabel: ":9012", url: "http://localhost:9012" },
  { label: "AceTutor", sublabel: ":9013", url: "http://localhost:9013" },
  { label: "City of Riverside", sublabel: ":9014", url: "http://localhost:9014" },
  { label: "HandyPro", sublabel: ":9015", url: "http://localhost:9015" },
  { label: "Dance Studio", sublabel: ":9016", url: "http://localhost:9016" },
  { label: "Your Pod (default)", sublabel: ":9000", url: "http://localhost:9000" },
];

export default function LoginPage() {
  const { login } = useAuth();
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isPending, setIsPending] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [selectedPod, setSelectedPod] = useState(() => {
    const stored = typeof window !== "undefined" ? getPodUrl() : "";
    // Default to :9001 (first multi-pod) if stored is :9000 or empty
    if (!stored || stored === "http://localhost:9000") return "http://localhost:9001";
    return stored;
  });
  const dropdownRef = useRef<HTMLDivElement>(null);

  const selectedPodInfo = DEMO_PODS.find(p => p.url === selectedPod) ?? DEMO_PODS[0];

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const handleSubmit = async () => {
    setError("");
    setPodUrl(selectedPod);
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
    <div className="min-h-screen flex flex-col">
      <nav className="flex items-center justify-between px-4 sm:px-6 py-3">
        <Link href="/" className="text-base font-bold tracking-tight text-gradient">
          TrustMesh
        </Link>
        <Link
          href="/signup"
          className="px-3 sm:px-4 py-1.5 bg-accent hover:bg-accent-hover text-accent-fg font-medium rounded-lg text-xs sm:text-sm transition-all"
        >
          Sign Up
        </Link>
      </nav>

      <div className="flex-1 flex items-center justify-center px-4 py-12">
        <div className="w-full max-w-md">
          <div className="bg-card border border-card-border rounded-2xl p-6 sm:p-8 shadow-xl shadow-black/20">
            <h1 className="text-xl sm:text-2xl font-bold mb-1">Welcome back</h1>
            <p className="text-xs sm:text-sm text-muted-foreground mb-6">
              Select your pod, then log in.
            </p>

            {error && (
              <div className="text-danger text-sm mb-4 p-3 bg-danger-dim rounded-lg border border-danger/20">
                {error}
              </div>
            )}

            <div className="space-y-4 mb-6">
              {/* Custom pod dropdown */}
              <div>
                <label className="block text-sm text-muted-foreground mb-1.5 font-medium">
                  Pod
                </label>
                <div ref={dropdownRef} className="relative">
                  <button
                    type="button"
                    onClick={() => setDropdownOpen(o => !o)}
                    className="w-full flex items-center justify-between bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm text-foreground focus:outline-none focus:border-accent/50 transition-colors hover:border-accent/30"
                  >
                    <span className="flex items-center gap-2">
                      <span>{selectedPodInfo.label}</span>
                      <span className="text-muted-foreground font-mono text-xs">{selectedPodInfo.sublabel}</span>
                    </span>
                    <ChevronDown size={14} className={`text-muted-foreground transition-transform ${dropdownOpen ? "rotate-180" : ""}`} />
                  </button>

                  {dropdownOpen && (
                    <div className="absolute z-50 top-full mt-1 left-0 right-0 bg-card border border-card-border rounded-xl shadow-2xl overflow-hidden max-h-64 overflow-y-auto">
                      {DEMO_PODS.map(p => (
                        <button
                          key={p.url}
                          type="button"
                          onClick={() => { setSelectedPod(p.url); setDropdownOpen(false); }}
                          className="w-full flex items-center justify-between px-4 py-2.5 text-sm text-left hover:bg-card-hover transition-colors"
                        >
                          <span className="flex items-center gap-2">
                            <span className={selectedPod === p.url ? "text-accent font-medium" : "text-foreground"}>
                              {p.label}
                            </span>
                            <span className="text-muted-foreground font-mono text-xs">{p.sublabel}</span>
                          </span>
                          {selectedPod === p.url && <Check size={13} className="text-accent shrink-0" />}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <div>
                <label className="block text-sm text-muted-foreground mb-1.5 font-medium">
                  Name, email, or @handle
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g., molly"
                  className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:border-accent/50 transition-colors autofill-fix"
                  onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
                  autoFocus
                  autoComplete="username"
                />
              </div>
              <div>
                <label className="block text-sm text-muted-foreground mb-1.5 font-medium">
                  Password
                </label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Your password"
                  className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:border-accent/50 transition-colors autofill-fix"
                  onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
                  autoComplete="current-password"
                />
              </div>
            </div>

            <button
              onClick={handleSubmit}
              disabled={!name.trim() || !password.trim() || isPending}
              className="w-full py-2.5 bg-accent hover:bg-accent-hover text-accent-fg font-semibold rounded-xl text-sm disabled:opacity-40 disabled:cursor-not-allowed transition-all hover:shadow-lg hover:shadow-accent/25 mb-4"
            >
              {isPending ? (
                <span className="flex items-center justify-center gap-2">
                  <Loader2 className="animate-spin" size={16} />
                  Authenticating...
                </span>
              ) : (
                "Log In"
              )}
            </button>

            <p className="text-center text-xs text-muted-foreground">
              Don&apos;t have an account?{" "}
              <Link href="/signup" className="text-accent hover:text-accent-hover transition-colors">
                Sign up
              </Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
