"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, type User } from "./api";

interface AuthContextValue {
  user: User | null;
  isLoading: boolean;
  login: (name: string, password: string) => Promise<User>;
  loginAsDemo: (username: string, password: string) => Promise<User>;
  signup: (data: { display_name: string; bio: string; password: string; email?: string; avatar_url?: string }) => Promise<User>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Check for existing session via httpOnly cookie on mount
  useEffect(() => {
    api.getMe()
      .then((me) => setUser(me))
      .catch(() => setUser(null))
      .finally(() => setIsLoading(false));
  }, []);

  const login = useCallback(async (name: string, password: string): Promise<User> => {
    const loggedIn = await api.login(name, password);
    setUser(loggedIn);
    return loggedIn;
  }, []);

  const loginAsDemo = useCallback(async (username: string, password: string): Promise<User> => {
    // Demo login sends username field for backward compat with demo pods
    const loggedIn = await api.login(username, password);
    setUser(loggedIn);
    return loggedIn;
  }, []);

  const signup = useCallback(async (data: { display_name: string; bio: string; password: string; email?: string; avatar_url?: string }): Promise<User> => {
    const newUser = await api.createUser(data);
    setUser(newUser);
    return newUser;
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      // Ignore — server session may already be gone
    }
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, isLoading, login, loginAsDemo, signup, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
