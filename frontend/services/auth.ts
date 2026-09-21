import { User, Session, LoginRequest, RegisterRequest, AuthResponse } from "@/types/auth";
import { api } from "@/utils/api";

export const AuthService = {
  async login(request: LoginRequest): Promise<AuthResponse> {
    const email = request.email.toLowerCase().trim();

    // 1. Call login endpoint — backend establishes HttpOnly auth_token & csrf_token cookies
    const loginRes = await api.post("/auth/login", {
      email,
      password: request.password,
    });

    const data = loginRes.data;
    const user: User = {
      id: data.uuid,
      name: data.full_name,
      email: data.email,
      role: data.role,
      organization: data.organization,
      preferredLanguage: data.preferred_language || "en",
      createdAt: data.created_at,
    };

    const expiresAt = new Date();
    expiresAt.setDate(expiresAt.getDate() + 7);

    const session: Session = {
      token: "", // Token stored securely in HttpOnly cookie; not exposed to JavaScript
      user,
      expiresAt: expiresAt.toISOString(),
    };

    return { user, session };
  },

  async register(request: RegisterRequest): Promise<AuthResponse> {
    const email = request.email.toLowerCase().trim();

    // 1. Call register endpoint — backend registers user and sets HttpOnly cookies
    const registerRes = await api.post("/auth/register", {
      email,
      password: request.password,
      full_name: request.name,
      organization: request.organization || "Personal Workspace",
      preferred_language: request.preferredLanguage || "en",
    });

    const data = registerRes.data;
    const user: User = {
      id: data.uuid,
      name: data.full_name,
      email: data.email,
      role: data.role,
      organization: data.organization,
      preferredLanguage: data.preferred_language || "en",
      createdAt: data.created_at,
    };

    const expiresAt = new Date();
    expiresAt.setDate(expiresAt.getDate() + 7);

    const session: Session = {
      token: "",
      user,
      expiresAt: expiresAt.toISOString(),
    };

    return { user, session };
  },

  async logout(): Promise<void> {
    try {
      await api.post("/auth/logout");
    } catch (e) {
      console.error("Backend logout request failed:", e);
    }
  },

  async verifySession(): Promise<Session | null> {
    if (typeof window === "undefined") return null;

    try {
      // Calls /auth/me with browser-managed HttpOnly credentials
      const res = await api.get("/auth/me");

      const user: User = {
        id: res.data.uuid,
        name: res.data.full_name,
        email: res.data.email,
        role: res.data.role,
        organization: res.data.organization,
        preferredLanguage: res.data.preferred_language || "en",
        createdAt: res.data.created_at,
      };

      const expiresAt = new Date();
      expiresAt.setDate(expiresAt.getDate() + 7);

      return {
        token: "",
        user,
        expiresAt: expiresAt.toISOString(),
      };
    } catch (err: any) {
      if (err.response && [400, 401, 403].includes(err.response.status)) {
        return null;
      }
      return null;
    }
  },

  updateLocalSessionUser(updatedUser: User): void {
    // Session state maintained in React AuthContext
  },

  async forgotPassword(email: string): Promise<void> {
    await api.post("/auth/forgot-password", {
      email: email.toLowerCase().trim(),
    });
  },

  async resetPassword(token: string, newPassword: string): Promise<void> {
    await api.post("/auth/reset-password", {
      token: token.trim(),
      new_password: newPassword,
    });
  },
};
