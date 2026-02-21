"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:9000";

interface InviteInfo {
  valid: boolean;
  network_id: string;
  network_name: string;
  invited_by: string;
  email: string;
}

export default function InvitePage() {
  const { token } = useParams<{ token: string }>();
  const router = useRouter();
  const [invite, setInvite] = useState<InviteInfo | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  // Signup form
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [bio, setBio] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/api/invite/${token}`)
      .then((r) => {
        if (!r.ok) throw new Error("Invalid invite");
        return r.json();
      })
      .then((data) => {
        setInvite(data);
        setLoading(false);
      })
      .catch(() => {
        setError("This invite link is invalid or has expired.");
        setLoading(false);
      });
  }, [token]);

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username || !displayName || !password) return;
    setSubmitting(true);
    setError("");

    try {
      // Create user
      const createRes = await fetch(`${API_BASE}/api/users`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          username,
          display_name: displayName,
          bio,
          password,
        }),
      });

      if (!createRes.ok) {
        const body = await createRes.json();
        throw new Error(body.detail || "Signup failed");
      }

      const user = await createRes.json();

      // Accept invite (join the network)
      const acceptRes = await fetch(`${API_BASE}/api/invite/${token}/accept`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
      });

      if (!acceptRes.ok) {
        throw new Error("Failed to join network");
      }

      setSuccess(true);
      // Redirect to dashboard after 2s
      setTimeout(() => router.push(`/${user.id}`), 2000);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="text-muted-foreground animate-pulse">Validating invite...</div>
      </div>
    );
  }

  if (error && !invite) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="max-w-md text-center">
          <h1 className="text-xl font-bold mb-2 text-danger">Invalid Invite</h1>
          <p className="text-muted-foreground mb-4">{error}</p>
          <Link href="/" className="text-accent hover:underline">Go to TrustMesh</Link>
        </div>
      </div>
    );
  }

  if (success) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="max-w-md text-center">
          <div className="w-16 h-16 rounded-full bg-green-500/20 flex items-center justify-center mx-auto mb-4">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-green-400">
              <polyline points="20 6 9 17 4 12"/>
            </svg>
          </div>
          <h1 className="text-xl font-bold mb-2">Welcome to {invite?.network_name}!</h1>
          <p className="text-muted-foreground">Redirecting to your dashboard...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <div className="max-w-md w-full">
        {/* Invite header */}
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-accent mb-1">TrustMesh</h1>
          <p className="text-sm text-muted-foreground">Trust-Aware Knowledge Sharing</p>
        </div>

        <div className="bg-card border border-card-border rounded-2xl p-6 mb-6">
          <div className="text-center mb-6">
            <div className="w-12 h-12 rounded-xl bg-accent/15 flex items-center justify-center mx-auto mb-3">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-accent">
                <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
                <circle cx="9" cy="7" r="4"/>
                <line x1="19" y1="8" x2="19" y2="14"/>
                <line x1="22" y1="11" x2="16" y2="11"/>
              </svg>
            </div>
            <h2 className="text-lg font-semibold">
              {invite?.invited_by} invited you to join
            </h2>
            <p className="text-accent font-bold text-xl mt-1">{invite?.network_name}</p>
          </div>

          <form onSubmit={handleSignup} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-muted-foreground mb-1">Username</label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ""))}
                placeholder="johndoe"
                className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-muted-foreground mb-1">Display Name</label>
              <input
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="John Doe"
                className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-muted-foreground mb-1">Bio (tell your agent about yourself)</label>
              <textarea
                value={bio}
                onChange={(e) => setBio(e.target.value)}
                placeholder="Software engineer, dad of one. Into hiking and woodworking."
                className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm h-20 resize-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-muted-foreground mb-1">Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Choose a password"
                className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm"
                required
                minLength={6}
              />
            </div>

            {error && (
              <p className="text-sm text-danger">{error}</p>
            )}

            <button
              type="submit"
              disabled={submitting || !username || !displayName || !password}
              className="w-full py-3 bg-accent hover:bg-accent-hover text-accent-fg font-semibold rounded-xl transition-all disabled:opacity-50"
            >
              {submitting ? "Creating your account..." : `Sign Up & Join ${invite?.network_name}`}
            </button>
          </form>
        </div>

        <p className="text-center text-xs text-muted-foreground">
          Already have an account?{" "}
          <Link href="/" className="text-accent hover:underline">Log in</Link>
        </p>
      </div>
    </div>
  );
}
