export type Role = "admin" | "employee" | "manager" | "viewer";

export interface Permissions {
  canViewDashboard: boolean;
  canChat: boolean;
  canManageDocuments: boolean;
  canUpload: boolean;
  canViewAnalytics: boolean;
  canManageSettings: boolean;
  canManageModels: boolean;
}

export interface User {
  id: string;
  name: string;
  email: string;
  role: Role;
  avatar?: string;
  organization: string;
  preferredLanguage: "en" | "ar";
  jobTitle?: string;
  createdAt: string;
}

export interface LoginRequest {
  email: string;
  password?: string;
}

export interface RegisterRequest {
  name: string;
  email: string;
  organization: string;
  jobTitle?: string;
  preferredLanguage: "en" | "ar";
  password?: string;
}

export interface Session {
  token: string;
  user: User;
  expiresAt: string;
}

export interface AuthResponse {
  user: User;
  session: Session;
}
