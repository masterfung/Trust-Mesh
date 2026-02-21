"use client";

import { useState, useRef } from "react";
import { useParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { UserAvatar } from "@/components/UserAvatar";
import { Loader2 } from "lucide-react";

function validateName(name: string): string | null {
  if (!name.trim()) return "Name is required";
  if (!/^[A-Za-z][A-Za-z \-'.]+$/.test(name.trim())) return "Letters only (spaces, hyphens, apostrophes OK)";
  return null;
}

export default function ProfilePage() {
  const { userId } = useParams<{ userId: string }>();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { data: user, isLoading } = useQuery({
    queryKey: ["user", userId],
    queryFn: () => api.getUser(userId),
  });

  const [displayName, setDisplayName] = useState<string | null>(null);
  const [email, setEmail] = useState<string | null>(null);
  const [bio, setBio] = useState<string | null>(null);
  const [avatarPreview, setAvatarPreview] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [avatarError, setAvatarError] = useState("");

  // Derived values: use local state if edited, otherwise user data
  const currentName = displayName ?? user?.display_name ?? "";
  const currentEmail = email ?? user?.email ?? "";
  const currentBio = bio ?? user?.bio ?? "";
  const currentAvatar = avatarPreview ?? user?.avatar_url ?? null;

  const nameError = currentName ? validateName(currentName) : null;
  const hasChanges = displayName !== null || email !== null || bio !== null || avatarPreview !== null;

  const handleAvatarChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setAvatarError("");
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 500_000) { setAvatarError("Image must be under 500KB"); return; }
    if (!file.type.startsWith("image/")) { setAvatarError("File must be an image"); return; }
    const reader = new FileReader();
    reader.onload = () => setAvatarPreview(reader.result as string);
    reader.readAsDataURL(file);
  };

  const saveMutation = useMutation({
    mutationFn: async () => {
      const updates: Record<string, string | undefined> = {};
      if (displayName !== null) updates.display_name = displayName.trim();
      if (email !== null) updates.email = email.trim() || undefined;
      if (bio !== null) updates.bio = bio;
      if (avatarPreview !== null) updates.avatar_url = avatarPreview;
      return api.updateUser(userId, updates);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["user", userId] });
      setDisplayName(null);
      setEmail(null);
      setBio(null);
      setAvatarPreview(null);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="animate-spin text-muted-foreground" size={24} />
      </div>
    );
  }

  if (!user) return <div className="p-8 text-muted-foreground">User not found</div>;

  return (
    <div className="max-w-2xl mx-auto p-6 md:p-8">
      <h1 className="text-2xl font-bold mb-1">Profile</h1>
      <p className="text-sm text-muted-foreground mb-8">Manage your personal information.</p>

      <div className="space-y-8">
        {/* Avatar */}
        <div className="flex items-center gap-5">
          <label className="group relative cursor-pointer">
            <UserAvatar user={{ ...user, avatar_url: currentAvatar }} size="xl" className="pointer-events-none" />
            <div className="absolute inset-0 rounded-xl bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center pointer-events-none">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
                <circle cx="12" cy="13" r="4" />
              </svg>
            </div>
            <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={handleAvatarChange} />
          </label>
          <div>
            <p className="text-sm font-medium">{user.display_name}</p>
            <p className="text-xs text-muted-foreground">
              {user.username ? `@${user.username}` : "Private account"}
              {user.email && ` \u00B7 ${user.email}`}
            </p>
            <button onClick={() => fileInputRef.current?.click()} className="text-xs text-accent hover:text-accent-hover mt-1 transition-colors">
              Change photo
            </button>
            {avatarError && <p className="text-xs text-danger mt-1">{avatarError}</p>}
          </div>
        </div>

        {/* Name */}
        <div>
          <label className="block text-sm font-medium mb-1.5">Display Name</label>
          <input
            type="text"
            value={currentName}
            onChange={(e) => setDisplayName(e.target.value)}
            className={`w-full bg-background border rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-accent/50 ${
              nameError ? "border-danger/50" : "border-card-border focus:border-accent/50"
            }`}
          />
          {nameError && <p className="text-xs text-danger mt-1">{nameError}</p>}
        </div>

        {/* Email */}
        <div>
          <label className="block text-sm font-medium mb-1.5">Email</label>
          <input
            type="email"
            value={currentEmail}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-accent/50 focus:border-accent/50"
          />
          <p className="text-xs text-muted-foreground mt-1">Used for account recovery. Never shared with others.</p>
        </div>

        {/* Bio */}
        <div>
          <label className="block text-sm font-medium mb-1.5">Bio</label>
          <textarea
            value={currentBio}
            onChange={(e) => setBio(e.target.value)}
            rows={3}
            placeholder="Tell your agent about yourself..."
            className="w-full bg-background border border-card-border rounded-xl px-4 py-2.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-accent/50 focus:border-accent/50 resize-none"
          />
        </div>

        {/* Save */}
        <div className="flex items-center gap-3">
          <button
            onClick={() => saveMutation.mutate()}
            disabled={!hasChanges || !!nameError || saveMutation.isPending}
            className="px-6 py-2.5 bg-accent hover:bg-accent-hover text-accent-fg font-semibold rounded-xl text-sm disabled:opacity-40 disabled:cursor-not-allowed transition-all hover:shadow-lg hover:shadow-accent/25"
          >
            {saveMutation.isPending ? (
              <span className="flex items-center gap-2">
                <Loader2 className="animate-spin" size={14} />
                Saving...
              </span>
            ) : "Save Changes"}
          </button>
          {saved && <span className="text-sm text-green-400">Saved</span>}
          {saveMutation.isError && <span className="text-sm text-danger">{saveMutation.error.message}</span>}
        </div>

        {/* Account Info (read-only) */}
        <div className="pt-4 border-t border-card-border">
          <h2 className="text-sm font-semibold mb-3 text-muted-foreground">Account Info</h2>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Account type</span>
              <span className="capitalize">{user.user_type || "person"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Public handle</span>
              <span>{user.username ? `@${user.username}` : "Not set \u2014 Go Live in Settings"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Created</span>
              <span>{user.created_at ? new Date(user.created_at).toLocaleDateString() : "Unknown"}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
