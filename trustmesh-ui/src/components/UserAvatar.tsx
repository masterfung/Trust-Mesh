"use client";

import type { User } from "@/lib/api";

interface UserAvatarProps {
  user: Pick<User, "display_name" | "avatar_url">;
  size?: "sm" | "md" | "lg" | "xl";
  className?: string;
}

const sizes = {
  sm: "w-7 h-7 text-xs",
  md: "w-9 h-9 text-sm",
  lg: "w-14 h-14 text-lg",
  xl: "w-20 h-20 text-2xl",
};

export function UserAvatar({ user, size = "md", className = "" }: UserAvatarProps) {
  const sizeClass = sizes[size];
  const initial = user.display_name?.[0]?.toUpperCase() || "?";

  if (user.avatar_url) {
    return (
      <img
        src={user.avatar_url}
        alt={user.display_name}
        className={`${sizeClass} rounded-xl object-cover shrink-0 ${className}`}
      />
    );
  }

  return (
    <div className={`${sizeClass} rounded-xl bg-accent flex items-center justify-center text-accent-fg font-bold shrink-0 ${className}`}>
      {initial}
    </div>
  );
}
