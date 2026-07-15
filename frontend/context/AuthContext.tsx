"use client";

import React, { createContext, useContext, useState, useEffect } from "react";
import { User, LoginRequest, RegisterRequest } from "@/types/auth";
import { AuthService } from "@/services/auth";
import { useRouter } from "next/navigation";

interface AuthContextType {
  currentUser: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (request: LoginRequest) => Promise<void>;
  register: (request: RegisterRequest) => Promise<void>;
  logout: () => Promise<void>;
  updateUser: (user: User) => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const router = useRouter();

  // Verify session on mount
  useEffect(() => {
    async function initAuth() {
      try {
        const session = await AuthService.verifySession();
        if (session) {
          setCurrentUser(session.user);
          
          const path = window.location.pathname;
          if (path === "/login" || path === "/register" || path === "/forgot-password" || path === "/session-expired") {
            router.push(session.user.organization ? "/dashboard" : "/select-workspace");
          }
        } else {
          setCurrentUser(null);
        }
      } catch (err) {
        console.error("Auth initialization failed:", err);
        setCurrentUser(null);
      } finally {
        setIsLoading(false);
      }
    }
    initAuth();
  }, [router]);

  const login = async (request: LoginRequest) => {
    setIsLoading(true);
    try {
      const response = await AuthService.login(request);
      setCurrentUser(response.user);
      router.push("/select-workspace");
    } catch (error) {
      setIsLoading(false);
      throw error;
    } finally {
      setIsLoading(false);
    }
  };

  const register = async (request: RegisterRequest) => {
    setIsLoading(true);
    try {
      const response = await AuthService.register(request);
      setCurrentUser(response.user);
      router.push("/select-workspace");
    } catch (error) {
      setIsLoading(false);
      throw error;
    } finally {
      setIsLoading(false);
    }
  };

  const logout = async () => {
    setIsLoading(true);
    try {
      await AuthService.logout();
      setCurrentUser(null);
      router.push("/login");
    } catch (error) {
      console.error("Logout failed:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const updateUser = (user: User) => {
    setCurrentUser(user);
    AuthService.updateLocalSessionUser(user);
  };

  return (
    <AuthContext.Provider
      value={{
        currentUser,
        isAuthenticated: !!currentUser,
        isLoading,
        login,
        register,
        logout,
        updateUser,
      }}
    >
      {isLoading ? (
        <div className="min-h-screen w-full flex flex-col items-center justify-center bg-slate-950 text-white gap-4">
          <div 
            className="flex h-16 w-16 items-center justify-center bg-primary text-primary-foreground font-bold text-3xl rounded-2xl animate-bounce"
            style={{
              boxShadow: "0 10px 25px -5px rgba(var(--color-primary), 0.3)",
              animationDuration: "2s"
            }}
          >
            🤖
          </div>
          <div className="flex flex-col items-center gap-1">
            <span className="text-sm font-bold tracking-tight">ArabIQ</span>
            <span className="text-[10px] text-zinc-400 font-bold uppercase tracking-wider">Verifying security session...</span>
          </div>
        </div>
      ) : (
        children
      )}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}

