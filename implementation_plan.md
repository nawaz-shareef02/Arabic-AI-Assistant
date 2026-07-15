# ArabIQ Backend-Readiness Refactoring Implementation Plan

This sprint refactors the ArabIQ frontend to remove all simulated/fake backend behaviors. Every view will consume data strictly through clean service files, displaying professional empty states, loading skeletons, and system offline/waiting indicators.

---

## Proposed Changes

### 1. Service Layer API Preparation

Create clean, structured TypeScript service modules under `frontend/services/` that initially return empty structures (simulating an offline/unconnected backend).

- **[NEW] [chat.ts](file:///d:/Arabic-NLP/frontend/services/chat.ts)**: Methods for messaging, fetching history/sessions. Returns empty arrays or connection errors.
- **[NEW] [documents.ts](file:///d:/Arabic-NLP/frontend/services/documents.ts)**: Methods for document management, returns empty collections.
- **[NEW] [knowledge-base.ts](file:///d:/Arabic-NLP/frontend/services/knowledge-base.ts)**: Methods for workspace knowledge collections.
- **[NEW] [dashboard.ts](file:///d:/Arabic-NLP/frontend/services/dashboard.ts)**: Methods for dashboard cards, returning 0 values.
- **[NEW] [analytics.ts](file:///d:/Arabic-NLP/frontend/services/analytics.ts)**: Methods for graphs, returning empty histories.
- **[NEW] [models.ts](file:///d:/Arabic-NLP/frontend/services/models.ts)**: Methods for listing LLMs, returning offline status flags.
- **[NEW] [health.ts](file:///d:/Arabic-NLP/frontend/services/health.ts)**: Service checking health endpoints for API, Ollama, Qdrant, Postgres, and Redis. All default to `waiting` status.

---

### 2. Sidebar & Navigation Components

Refactor dashboard components to read from the new services and display unconnected status banners.

- **[MODIFY] [StorageCard.tsx](file:///d:/Arabic-NLP/frontend/components/dashboard/StorageCard.tsx)**:
  - Display: "0 MB Used", "0 Documents", "No uploads yet" and an empty progress bar.
- **[MODIFY] [ModelStatus.tsx](file:///d:/Arabic-NLP/frontend/components/dashboard/ModelStatus.tsx)**:
  - Display: "Checking AI Server..." on mount.
  - Settle on: "⚪ No AI Model Connected", "Waiting for Ollama Connection".
  - Include: "Last Checked: <time>" and a functional "Retry Connection" button.
- **[MODIFY] [NotificationBell.tsx](file:///d:/Arabic-NLP/frontend/components/dashboard/NotificationBell.tsx)**:
  - Initialize empty, display "No Notifications".

---

### 3. Application Pages Refactoring

Implement robust, professional frontend interfaces that visually disable actions and explicitly advise backend connection requirements.

- **[MODIFY] [page.tsx](file:///d:/Arabic-NLP/frontend/app/chat/page.tsx)**:
  - Implement a premium Chat screen layout.
  - If backend is offline: display central info card: *"Enterprise AI Assistant. Backend connection required. Connect FastAPI and Ollama to begin chatting."*
  - Disable input text field and Send buttons.
  - Display alert badge: *"Waiting for AI Backend..."*
- **[MODIFY] [page.tsx](file:///d:/Arabic-NLP/frontend/app/dashboard/page.tsx)**:
  - Replace text placeholder with actual stats cards displaying all 0 stats.
  - Display empty state panel: *"No Activity Yet. Start by uploading your first document."*
  - Render a professional **System Status** dashboard widget listing the status of all five infrastructure services (API, Ollama, Qdrant, Postgres, Redis) as *"Waiting for Backend..."*.
- **[MODIFY] [page.tsx](file:///d:/Arabic-NLP/frontend/app/documents/page.tsx)**:
  - Bind documents and collections to the new services.
  - Show empty file lists: *"No Documents Uploaded. Upload your first PDF, DOCX or TXT file."* with custom illustrations and an "Upload Document" button.
  - Show empty knowledge bases: *"No Knowledge Bases. Create your first Knowledge Base."* with a "Create Knowledge Base" button.
- **[MODIFY] [page.tsx](file:///d:/Arabic-NLP/frontend/app/upload/page.tsx)**:
  - Implement a drag-and-drop file upload screen but disable all drops and triggers.
  - Display warning overlay: *"Upload service unavailable. Backend connection required. After backend integration this page will upload files."*
- **[MODIFY] [page.tsx](file:///d:/Arabic-NLP/frontend/app/analytics/page.tsx)**:
  - Refactor graphs to read from service, show empty state: *"No analytics available yet. Analytics will appear after AI usage."*
  - Show professional shimmer loading skeletons during data fetching states.
- **[MODIFY] [page.tsx](file:///d:/Arabic-NLP/frontend/app/models/page.tsx)**:
  - Render AI models list with "Waiting for Ollama" or "Offline" states.
- **[MODIFY] [AuthContext.tsx](file:///d:/Arabic-NLP/frontend/context/AuthContext.tsx)**:
  - Display *"Session not verified (Mock Auth)"* or similar status in profiles to represent a mock frontend state.

---

## Verification Plan

### Automated Tests
- Run `npm run build` to confirm compilation.

### Manual Verification
1. Open the dev dashboard: verify statistic counters show all 0s and System Status lists all backend components as "Waiting for Backend...".
2. Navigate to Chat: check disabled input field and connect warning banners.
3. Check the Sidebar widgets: Storage shows 0 MB, active model shows "No AI Model Connected (Waiting for Ollama Connection)" with a functional "Retry" button.
4. Verify Documents, Upload, and Analytics tabs reflect their polished empty states.
