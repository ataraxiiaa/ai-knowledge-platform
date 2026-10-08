"use client";

import React, { createContext, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  authApi,
  clearStoredToken,
  getStoredToken,
  getStoredUserEmail,
  setStoredToken,
} from "@/lib/api";

interface AuthContextType {
  token: string | null;
  userEmail: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [userEmail, setUserEmail] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const router = useRouter();

  useEffect(() => {
    const savedToken = getStoredToken();
    const savedEmail = getStoredUserEmail();
    if (savedToken) {
      setToken(savedToken);
      setUserEmail(savedEmail);
    }
    setIsLoading(false);
  }, []);

  const login = async (email: string, password: string) => {
    const data = await authApi.login(email, password);
    setStoredToken(data.access_token, email);
    setToken(data.access_token);
    setUserEmail(email);
    router.push("/");
  };

  const register = async (email: string, password: string) => {
    await authApi.register(email, password);
    // After registration, log in automatically
    await login(email, password);
  };

  const logout = () => {
    clearStoredToken();
    setToken(null);
    setUserEmail(null);
    router.push("/login");
  };

  return (
    <AuthContext.Provider
      value={{
        token,
        userEmail,
        isAuthenticated: !!token,
        isLoading,
        login,
        register,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
