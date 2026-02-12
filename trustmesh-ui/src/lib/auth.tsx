"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, type User } from "./api";

interface AuthContextValue {
  user: User | null;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<User>;
  loginAsDemo: (username: string, password: string) => Promise<User>;
  signup: (data: { username: string; display_name: string; bio: string; password: string }) => Promise<User>;
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

  const login = useCallback(async (username: string, password: string): Promise<User> => {
    const loggedIn = await api.login(username, password);
    setUser(loggedIn);
    return loggedIn;
  }, []);

  const loginAsDemo = useCallback(async (username: string, password: string): Promise<User> => {
    // Demo login uses the same server-side auth — cookie is set by the backend
    const loggedIn = await api.login(username, password);
    setUser(loggedIn);
    return loggedIn;
  }, []);

  const signup = useCallback(async (data: { username: string; display_name: string; bio: string; password: string }): Promise<User> => {
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
