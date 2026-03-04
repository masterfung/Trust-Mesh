"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth";
import Link from "next/link";
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

export default function SignupPage() {
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
  const isValid = displayName.trim() && !nameError && !passwordError && password.length >= 16;

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

  return (
    <div className="min-h-screen flex flex-col">
      <nav className="flex items-center justify-between px-4 sm:px-6 py-3">
        <Link href="/" className="text-base font-bold tracking-tight text-gradient">
          TrustMesh
        </Link>
        <Link
          href="/login"
          className="px-3 sm:px-4 py-1.5 text-xs sm:text-sm text-muted-foreground hover:text-foreground font-medium rounded-lg hover:bg-card transition-colors"
        >
          Log In
        </Link>
      </nav>

      <div className="flex-1 flex items-center justify-center px-4 py-12">
        <div className="w-full max-w-md">
          <div className="bg-card border border-card-border rounded-2xl p-6 sm:p-8 shadow-xl shadow-black/20">
            <h1 className="text-xl sm:text-2xl font-bold mb-1">Get started</h1>
            <p className="text-xs sm:text-sm text-muted-foreground mb-6">
              Your own AI assistant and private memories. Private by default.
            </p>

            {error && (
              <div className="text-danger text-sm mb-4 p-3 bg-danger-dim rounded-lg border border-danger/20">
                {error}
              </div>
            )}

            <div className="space-y-4 mb-6">
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
                  autoFocus
                  className={`w-full bg-background border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-accent/50 ${
                    nameError ? "border-danger/50" : "border-card-border focus:border-accent/50"
                  }`}
                />
                {nameError && <p className="text-xs text-danger mt-1">{nameError}</p>}
              </div>

              {/* Email */}
              <div>
                <label className="block text-sm text-muted-foreground mb-1.5 font-medium">
                  Email <span className="text-muted-foreground">(optional)</span>
                </label>
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
                <label className="block text-sm text-muted-foreground mb-1.5 font-medium">
                  About you <span className="text-muted-foreground">(optional)</span>
                </label>
                <input
                  type="text"
                  value={bio}
                  onChange={(e) => setBio(e.target.value)}
                  placeholder="A brief intro so your AI assistant can help you better..."
                  className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-accent/50 focus:border-accent/50"
                />
              </div>
            </div>

            <button
              onClick={() => mutation.mutate()}
              disabled={!isValid || mutation.isPending}
              className="w-full py-2.5 bg-accent hover:bg-accent-hover text-accent-fg font-semibold rounded-xl text-sm disabled:opacity-40 disabled:cursor-not-allowed transition-all hover:shadow-lg hover:shadow-accent/25 mb-4"
            >
              {mutation.isPending ? (
                <span className="flex items-center justify-center gap-2">
                  <Loader2 className="animate-spin" size={16} />
                  Creating your account...
                </span>
              ) : (
                "Create Account"
              )}
            </button>

            <p className="text-center text-xs text-muted-foreground">
              Already have an account?{" "}
              <Link href="/login" className="text-accent hover:text-accent-hover transition-colors">
                Log in
              </Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
