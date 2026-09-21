import axios from "axios";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

/**
 * Reads a specific cookie value by name in browser context.
 */
export function getCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(new RegExp("(^|;\\s*)(" + name + ")=([^;]*)"));
  return match ? decodeURIComponent(match[3]) : null;
}

/**
 * Retrieves the non-HttpOnly CSRF token cookie for double-submit header validation.
 */
export function getCsrfToken(): string | null {
  return getCookie("csrf_token");
}

export const api = axios.create({
  baseURL: `${API_URL}/api/v1`,
  withCredentials: true, // Automatically sends HttpOnly auth_token & csrf_token cookies
  headers: {
    "Content-Type": "application/json",
  },
});

// Request interceptor: automatically append X-CSRF-Token for mutating methods
api.interceptors.request.use(
  (config) => {
    if (typeof window !== "undefined") {
      const method = (config.method || "get").toUpperCase();
      const mutatingMethods = ["POST", "PUT", "PATCH", "DELETE"];

      if (mutatingMethods.includes(method)) {
        const csrfToken = getCsrfToken();
        if (csrfToken) {
          config.headers["X-CSRF-Token"] = csrfToken;
        }
      }
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor to handle unhandled 401s and redirect to session-expired
api.interceptors.response.use(
  (response) => {
    return response;
  },
  (error) => {
    if (error.response && error.response.status === 401) {
      if (typeof window !== "undefined") {
        const url: string = error.config?.url || "";
        // Skip redirect for auth-related endpoints — their 401s are handled by callers
        const isAuthEndpoint = url.includes("/auth/");
        if (!isAuthEndpoint) {
          const path = window.location.pathname;
          if (path !== "/login" && path !== "/session-expired" && path !== "/register") {
            window.location.href = "/session-expired";
          }
        }
      }
    }
    return Promise.reject(error);
  }
);
