"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Sidebar } from "@/components/Sidebar";
import { useParams } from "next/navigation";

export default function UserLayout({ children }: { children: React.ReactNode }) {
  const params = useParams();
  const userId = params.userId as string;

  const { data: user, isLoading } = useQuery({
    queryKey: ["user", userId],
    queryFn: () => api.getUser(userId),
  });

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-muted animate-pulse">Loading...</div>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-danger">User not found</div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen">
      <Sidebar user={user} />
      <main className="flex-1 p-6 overflow-auto">{children}</main>
    </div>
  );
}
