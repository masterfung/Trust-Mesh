"use client";

import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Sidebar } from "@/components/Sidebar";
import { useParams, useRouter } from "next/navigation";

export default function UserLayout({ children }: { children: React.ReactNode }) {
  const params = useParams();
  const router = useRouter();
  const userId = params.userId as string;
  const { user: authUser, isLoading: authLoading } = useAuth();

  const { data: user, isLoading } = useQuery({
    queryKey: ["user", userId],
    queryFn: () => api.getUser(userId),
  });

  // Redirect to landing if not authenticated
  useEffect(() => {
    if (!authLoading && !authUser) {
      router.push("/");
    }
  }, [authUser, authLoading, router]);

  // Redirect if trying to access another user's dashboard
  useEffect(() => {
    if (!authLoading && authUser && authUser.id !== userId) {
      router.push(`/${authUser.id}`);
    }
  }, [authUser, authLoading, userId, router]);

  if (authLoading || isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-muted animate-pulse">Loading...</div>
      </div>
    );
  }

  if (!authUser) {
    return null; // Will redirect
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
      <main className="flex-1 p-4 md:p-8 overflow-auto">{children}</main>
    </div>
  );
}
