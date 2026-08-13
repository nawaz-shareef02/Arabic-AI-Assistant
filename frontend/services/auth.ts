import { User, Session, LoginRequest, RegisterRequest, AuthResponse } from "@/types/auth";
import { api } from "@/utils/api";

const SESSION_KEY = "arabiq_user_session";
const COOKIE_NAME = "arabiq-session";

// Helpers for cookies
const setSessionCookie = (token: string, days = 7) => {
  if (typeof document === "undefined") return;
  const expires = new Date();
  expires.setTime(expires.getTime() + days * 24 * 60 * 60 * 1000);
  document.cookie = `${COOKIE_NAME}=${token};path=/;expires=${expires.toUTCString()};SameSite=Lax`;
};

const deleteSessionCookie = () => {
  if (typeof document === "undefined") return;
  document.cookie = `${COOKIE_NAME}=;path=/;expires=Thu, 01 Jan 1970 00:00:01 GMT`;
};

const getSessionCookie = (): string | null => {
  if (typeof document === "undefined") return null;
  const nameEQ = COOKIE_NAME + "=";
  const ca = document.cookie.split(";");
  for (let i = 0; i < ca.length; i++) {
    let c = ca[i];
    while (c.charAt(0) === " ") c = c.substring(1, c.length);
    if (c.indexOf(nameEQ) === 0) return c.substring(nameEQ.length, c.length);
  }
  return null;
};

export const AuthService = {
  async login(request: LoginRequest): Promise<AuthResponse> {
    const email = request.email.toLowerCase().trim();
    
    // 1. Call login endpoint to obtain access token
    const loginRes = await api.post("/auth/login", {
      email,
      password: request.password
    });
    
    const token = loginRes.data.access_token;
    
    // 2. Fetch authenticated user profile using token
    const profileRes = await api.get("/auth/me", {
      headers: {
        Authorization: `Bearer ${token}`
      }
    });
    
    const user: User = {
      id: profileRes.data.uuid, // Expose uuid as standard ID in frontend
      name: profileRes.data.full_name,
      email: profileRes.data.email,
      role: profileRes.data.role,
      organization: profileRes.data.organization,
      preferredLanguage: profileRes.data.preferred_language,
      createdAt: profileRes.data.created_at
    };

    const expiresAt = new Date();
    expiresAt.setDate(expiresAt.getDate() + 7);

    const session: Session = {
      token,
      user,
      expiresAt: expiresAt.toISOString(),
    };

    if (typeof window !== "undefined") {
      localStorage.setItem(SESSION_KEY, JSON.stringify(session));
      setSessionCookie(token, 7);
    }

    return { user, session };
  },

  async register(request: RegisterRequest): Promise<AuthResponse> {
    const email = request.email.toLowerCase().trim();

    // 1. Call register endpoint
    const registerRes = await api.post("/auth/register", {
      email,
      password: request.password,
      full_name: request.name,
      organization: request.organization || "Personal Workspace",
      preferred_language: request.preferredLanguage || "en"
    });

    // 2. Log in automatically to get token
    const loginRes = await api.post("/auth/login", {
      email,
      password: request.password
    });

    const token = loginRes.data.access_token;
    
    const user: User = {
      id: registerRes.data.uuid,
      name: registerRes.data.full_name,
      email: registerRes.data.email,
      role: registerRes.data.role,
      organization: registerRes.data.organization,
      preferredLanguage: registerRes.data.preferred_language,
      createdAt: registerRes.data.created_at
    };

    const expiresAt = new Date();
    expiresAt.setDate(expiresAt.getDate() + 7);

    const session: Session = {
      token,
      user,
      expiresAt: expiresAt.toISOString(),
    };

    if (typeof window !== "undefined") {
      localStorage.setItem(SESSION_KEY, JSON.stringify(session));
      setSessionCookie(token, 7);
    }

    return { user, session };
  },

  async logout(): Promise<void> {
    if (typeof window !== "undefined") {
      localStorage.removeItem(SESSION_KEY);
      deleteSessionCookie();
    }
  },

  async verifySession(): Promise<Session | null> {
    if (typeof window === "undefined") return null;

    const token = getSessionCookie();
    const sessionStr = localStorage.getItem(SESSION_KEY);

    if (!token || !sessionStr) {
      localStorage.removeItem(SESSION_KEY);
      deleteSessionCookie();
      return null;
    }

    let session: Session;
    try {
      session = JSON.parse(sessionStr);
      if (new Date(session.expiresAt) < new Date()) {
        localStorage.removeItem(SESSION_KEY);
        deleteSessionCookie();
        return null;
      }
    } catch {
      localStorage.removeItem(SESSION_KEY);
      deleteSessionCookie();
      return null;
    }

    try {
      const res = await api.get("/auth/me", {
        headers: {
          Authorization: `Bearer ${token}`
        }
      });
      
      const user: User = {
        id: res.data.uuid,
        name: res.data.full_name,
        email: res.data.email,
        role: res.data.role,
        organization: res.data.organization,
        preferredLanguage: res.data.preferred_language,
        createdAt: res.data.created_at
      };
      
      session.user = user;
      localStorage.setItem(SESSION_KEY, JSON.stringify(session));
      return session;
    } catch (err: any) {
      if (err.response && [400, 401, 403].includes(err.response.status)) {
        localStorage.removeItem(SESSION_KEY);
        deleteSessionCookie();
        return null;
      }
      console.warn("Transient backend exception detected. Retaining local session:", err);
      return session;
    }
  },

  updateLocalSessionUser(updatedUser: User): void {
    if (typeof window === "undefined") return;
    const sessionStr = localStorage.getItem(SESSION_KEY);
    if (sessionStr) {
      try {
        const session: Session = JSON.parse(sessionStr);
        session.user = updatedUser;
        localStorage.setItem(SESSION_KEY, JSON.stringify(session));
      } catch (e) {
        console.error("Error updating local session user", e);
      }
    }
  },

  async forgotPassword(email: string): Promise<void> {
    await api.post("/auth/forgot-password", {
      email: email.toLowerCase().trim()
    });
  },

  async resetPassword(token: string, newPassword: string): Promise<void> {
    await api.post("/auth/reset-password", {
      token: token.trim(),
      new_password: newPassword
    });
  }
};
