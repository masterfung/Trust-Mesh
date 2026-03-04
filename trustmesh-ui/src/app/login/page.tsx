"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth";
import Link from "next/link";
import { Loader2 } from "lucide-react";

export default function LoginPage() {
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
              Log in with your name, email, or handle.
            </p>

            {error && (
              <div className="text-danger text-sm mb-4 p-3 bg-danger-dim rounded-lg border border-danger/20">
                {error}
              </div>
            )}

            <div className="space-y-4 mb-6">
              <div>
                <label className="block text-sm text-muted-foreground mb-1.5 font-medium">
                  Name, email, or @handle
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g., Amy Lee or amy@email.com"
                  className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-accent/50 focus:border-accent/50"
                  onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
                  autoFocus
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
                  className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-accent/50 focus:border-accent/50"
                  onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
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
