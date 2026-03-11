"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth";
import { PodTypeCard } from "@/components/ui/pod-type-card";
import Link from "next/link";
import { Loader2, User, Building2 } from "lucide-react";
import Image from "next/image";

type Step = "type" | "personal" | "org";
type OrgSubtype = "company" | "nonprofit" | "healthcare" | "education" | "emergency" | "government";

const ORG_SUBTYPES: { key: OrgSubtype; label: string; badge?: string }[] = [
  { key: "company",    label: "Company" },
  { key: "nonprofit",  label: "Nonprofit" },
  { key: "healthcare", label: "Healthcare", badge: "🔑 Emergency access" },
  { key: "education",  label: "Education" },
  { key: "emergency",  label: "Emergency",  badge: "🔑 Emergency access" },
  { key: "government", label: "Government" },
];

function validatePasswordComplexity(pw: string): string | null {
  if (pw.length < 16) return "Password must be at least 16 characters";
  if (!/[A-Z]/.test(pw)) return "Must contain an uppercase letter";
  if (!/[a-z]/.test(pw)) return "Must contain a lowercase letter";
  if (!/[0-9]/.test(pw)) return "Must contain a digit";
  if (!/[^A-Za-z0-9]/.test(pw)) return "Must contain a special character (!@#$%^&* etc.)";
  return null;
}

function validatePersonName(name: string): string | null {
  if (!name.trim()) return null;
  if (!/^[A-Za-z][A-Za-z \-'.]+$/.test(name.trim())) return "Letters only (spaces, hyphens, apostrophes OK)";
  if (name.trim().split(/\s+/).length < 2) return "Please enter first and last name";
  return null;
}

function validateOrgName(name: string): string | null {
  if (!name.trim()) return null;
  if (!/^[A-Za-z][A-Za-z0-9 \-'&.,]+$/.test(name.trim())) return "Name may contain letters, numbers, spaces, and common punctuation";
  return null;
}

export default function SignupPage() {
  const { signup } = useAuth();
  const queryClient = useQueryClient();

  const [step, setStep] = useState<Step>("type");
  const [podType, setPodType] = useState<"person" | "org" | null>(null);
  const [orgSubtype, setOrgSubtype] = useState<OrgSubtype | null>(null);

  // Shared fields
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [bio, setBio] = useState("");
  const [password, setPassword] = useState("");
  const [avatarPreview, setAvatarPreview] = useState<string | null>(null);
  const [error, setError] = useState("");

  const isOrg = step === "org";
  const nameValidator = isOrg ? validateOrgName : validatePersonName;
  const passwordError = password.length > 0 ? validatePasswordComplexity(password) : null;
  const nameError = displayName.length > 0 ? nameValidator(displayName) : null;

  const isPersonValid = displayName.trim() && !nameError && !passwordError && password.length >= 16;
  const isOrgValid = displayName.trim() && !nameError && !passwordError && password.length >= 16 && orgSubtype !== null && email.trim();

  const isValid = isOrg ? isOrgValid : isPersonValid;

  const handleAvatarChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 500_000) { setError("Image must be under 500KB"); return; }
    const allowedTypes = ["image/jpeg", "image/png", "image/webp"];
    if (!allowedTypes.includes(file.type)) { setError("Only JPEG, PNG, or WEBP are allowed"); return; }
    const reader = new FileReader();
    reader.onload = () => { setAvatarPreview(reader.result as string); setError(""); };
    reader.readAsDataURL(file);
  };

  const mutation = useMutation({
    mutationFn: () => {
      return signup({
        display_name: displayName.trim(),
        bio,
        password,
        email: email || undefined,
        avatar_url: avatarPreview || undefined,
        user_type: isOrg ? "organization" : "person",
        org_subtype: isOrg && orgSubtype ? orgSubtype : undefined,
      });
    },
    onSuccess: (newUser) => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      window.location.href = `/${newUser.id}/onboard`;
    },
    onError: (err: Error) => setError(err.message),
  });

  // ── Step: type selector ──────────────────────────────────────────────────
  if (step === "type") {
    return (
      <div className="min-h-screen flex flex-col">
        <nav className="flex items-center justify-between px-4 sm:px-6 py-3">
          <Link href="/" className="text-base font-bold tracking-tight text-gradient">TrustMesh</Link>
          <Link href="/login" className="px-3 sm:px-4 py-1.5 text-xs sm:text-sm text-muted-foreground hover:text-foreground font-medium rounded-lg hover:bg-card transition-colors">
            Log In
          </Link>
        </nav>
        <div className="flex-1 flex items-center justify-center px-4 py-12">
          <div className="w-full max-w-md">
            <div className="bg-card border border-card-border rounded-2xl p-6 sm:p-8 shadow-xl shadow-black/20">
              <h1 className="text-xl sm:text-2xl font-bold mb-1">Choose your pod type</h1>
              <p className="text-xs sm:text-sm text-muted-foreground mb-6">
                Your pod type determines how your agent works and what it shares.
              </p>

              <div className="grid grid-cols-2 gap-3 mb-6">
                <PodTypeCard
                  selected={podType === "person"}
                  onClick={() => setPodType("person")}
                  badge="Most common"
                  icon={<User size={20} className="text-accent" />}
                  title="Personal Pod"
                  description="Private AI + encrypted vault. For individuals."
                />
                <PodTypeCard
                  selected={podType === "org"}
                  onClick={() => setPodType("org")}
                  icon={<Building2 size={20} className="text-amber-400" />}
                  title="Organization Pod"
                  description="Service agent + team knowledge. For businesses, nonprofits & gov."
                />
              </div>

              <button
                onClick={() => {
                  if (podType === "person") setStep("personal");
                  else if (podType === "org") setStep("org");
                }}
                disabled={!podType}
                className="w-full py-2.5 bg-accent hover:bg-accent-hover text-accent-fg font-semibold rounded-xl text-sm disabled:opacity-40 disabled:cursor-not-allowed transition-all hover:shadow-lg hover:shadow-accent/25"
              >
                Continue
              </button>

              <p className="text-center text-xs text-muted-foreground mt-4">
                Already have an account?{" "}
                <Link href="/login" className="text-accent hover:text-accent-hover transition-colors">Log in</Link>
              </p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ── Shared form shell ─────────────────────────────────────────────────────
  return (
    <div className="min-h-screen flex flex-col">
      <nav className="flex items-center justify-between px-4 sm:px-6 py-3">
        <Link href="/" className="text-base font-bold tracking-tight text-gradient">TrustMesh</Link>
        <Link href="/login" className="px-3 sm:px-4 py-1.5 text-xs sm:text-sm text-muted-foreground hover:text-foreground font-medium rounded-lg hover:bg-card transition-colors">
          Log In
        </Link>
      </nav>

      <div className="flex-1 flex items-center justify-center px-4 py-12">
        <div className="w-full max-w-md">
          <div className="bg-card border border-card-border rounded-2xl p-6 sm:p-8 shadow-xl shadow-black/20">
            {/* Back + heading */}
            <button
              onClick={() => setStep("type")}
              className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground mb-4 transition-colors"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <polyline points="15 18 9 12 15 6" />
              </svg>
              Back
            </button>

            <h1 className="text-xl sm:text-2xl font-bold mb-1">
              {isOrg ? "Set up your organization" : "Get started"}
            </h1>
            <p className="text-xs sm:text-sm text-muted-foreground mb-6">
              {isOrg
                ? "Your service agent starts in private mode. Enable public access from Settings."
                : "Your own AI assistant and private memories. Private by default."}
            </p>

            {error && (
              <div className="text-danger text-sm mb-4 p-3 bg-danger-dim rounded-lg border border-danger/20">
                {error}
              </div>
            )}

            <div className="space-y-4 mb-6">

              {/* Org subtype picker */}
              {isOrg && (
                <div>
                  <label className="block text-sm text-muted-foreground mb-1.5 font-medium">
                    Organization type <span className="text-danger text-xs">*</span>
                  </label>
                  <div className="flex flex-wrap gap-2">
                    {ORG_SUBTYPES.map(({ key, label, badge }) => (
                      <button
                        key={key}
                        type="button"
                        onClick={() => setOrgSubtype(key)}
                        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-xs font-medium transition-all ${
                          orgSubtype === key
                            ? "border-accent bg-accent/10 text-accent"
                            : "border-card-border bg-background text-muted-foreground hover:border-accent/40 hover:text-foreground"
                        }`}
                      >
                        {label}
                        {badge && <span className="text-[10px] opacity-70">{badge}</span>}
                      </button>
                    ))}
                  </div>
                  {isOrg && !orgSubtype && (
                    <p className="text-xs text-muted-foreground mt-1">Select your organization type to continue</p>
                  )}
                </div>
              )}

              {/* Avatar (persons only) */}
              {!isOrg && (
                <div className="flex items-center gap-4">
                  <label htmlFor="avatar-upload" className="cursor-pointer group relative">
                    <div className="w-14 h-14 sm:w-16 sm:h-16 rounded-full bg-background border-2 border-dashed border-card-border group-hover:border-accent/50 transition-colors flex items-center justify-center overflow-hidden">
                      {avatarPreview ? (
                        <Image src={avatarPreview} alt="Avatar" width={64} height={64} className="w-full h-full object-cover" />
                      ) : (
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-muted-foreground group-hover:text-accent transition-colors">
                          <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" />
                        </svg>
                      )}
                    </div>
                    <input id="avatar-upload" type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={handleAvatarChange} />
                  </label>
                  <div>
                    <p className="text-sm font-medium">Profile photo</p>
                    <p className="text-xs text-muted-foreground">
                      <label htmlFor="avatar-upload" className="cursor-pointer text-accent hover:text-accent-hover transition-colors">Upload photo</label> &middot; max 500KB
                    </p>
                  </div>
                </div>
              )}

              {/* Name */}
              <div>
                <label className="block text-sm text-muted-foreground mb-1.5 font-medium">
                  {isOrg ? "Organization name" : "Full Name"}
                </label>
                <input
                  type="text"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder={isOrg ? "e.g., City General Hospital" : "e.g., Amy Lee"}
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
                  Email {!isOrg && <span className="text-muted-foreground">(optional)</span>}
                  {isOrg && <span className="text-danger text-xs"> *</span>}
                </label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-accent/50 focus:border-accent/50"
                />
                <p className="text-xs text-muted-foreground mt-1">
                  {isOrg ? "Used for account recovery and org verification." : "For account recovery. Never shared."}
                </p>
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
                  <p className="text-xs text-muted-foreground mt-1">Protects your {isOrg ? "organization data" : "private memories"} with end-to-end encryption</p>
                )}
              </div>

              {/* Bio / Description */}
              <div>
                <label className="block text-sm text-muted-foreground mb-1.5 font-medium">
                  {isOrg ? "Description" : "About you"}{" "}
                  <span className="text-muted-foreground">(optional)</span>
                </label>
                <input
                  type="text"
                  value={bio}
                  onChange={(e) => setBio(e.target.value)}
                  placeholder={isOrg
                    ? "What your organization does..."
                    : "A brief intro so your AI assistant can help you better..."}
                  className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-accent/50 focus:border-accent/50"
                />
              </div>

              {isOrg && (
                <div className="flex items-start gap-2 p-3 rounded-xl bg-amber-500/5 border border-amber-500/20">
                  <Building2 size={14} className="text-amber-400 mt-0.5 shrink-0" />
                  <p className="text-xs text-amber-400/80">
                    Your agent starts in <strong>private mode</strong>. Enable public access from Settings → Agent Visibility to appear in the service directory.
                  </p>
                </div>
              )}
            </div>

            <button
              onClick={() => mutation.mutate()}
              disabled={!isValid || mutation.isPending}
              className="w-full py-2.5 bg-accent hover:bg-accent-hover text-accent-fg font-semibold rounded-xl text-sm disabled:opacity-40 disabled:cursor-not-allowed transition-all hover:shadow-lg hover:shadow-accent/25 mb-4"
            >
              {mutation.isPending ? (
                <span className="flex items-center justify-center gap-2">
                  <Loader2 className="animate-spin" size={16} />
                  Creating {isOrg ? "organization" : "account"}...
                </span>
              ) : (
                isOrg ? "Create Organization" : "Create Account"
              )}
            </button>

            <p className="text-center text-xs text-muted-foreground">
              Already have an account?{" "}
              <Link href="/login" className="text-accent hover:text-accent-hover transition-colors">Log in</Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
