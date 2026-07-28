import axios from "axios";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export const api = axios.create({
  baseURL: `${API_URL}/api/v1`,
  headers: {
    "Content-Type": "application/json",
  },
});

// Request interceptor to automatically append the JWT token from session storage
api.interceptors.request.use(
  (config) => {
    if (typeof window !== "undefined") {
      const sessionStr = localStorage.getItem("arabiq_user_session");
      if (sessionStr) {
        try {
          const session = JSON.parse(sessionStr);
          if (session.token) {
            config.headers.Authorization = `Bearer ${session.token}`;
          }
        } catch (e) {
          console.error("Error reading token from localStorage session", e);
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
          // Evict local authentication credentials
          localStorage.removeItem("arabiq_user_session");
          document.cookie = "arabiq-session=;path=/;expires=Thu, 01 Jan 1970 00:00:01 GMT";

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
