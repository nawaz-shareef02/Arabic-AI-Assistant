<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

<!-- BEGIN:auth-architecture-rules -->
## Authentication Architecture (P2-1 — Cookie-Based Auth)

**Cookie-based auth is active.** The JWT is stored in an HttpOnly cookie (`auth_token`) set by the FastAPI backend. It is NOT in `localStorage`, `sessionStorage`, or any JS-readable storage.

### DO NOT add any of the following
- `localStorage.setItem(...)` for JWTs, access tokens, or session tokens
- `sessionStorage.setItem(...)` for JWTs, access tokens, or session tokens
- Manual construction of `Authorization: Bearer <token>` headers from stored tokens
- Manually reading `document.cookie` to extract `auth_token` (it is HttpOnly — this will always return empty)

### Token transmission
- All Axios requests use `withCredentials: true` — the browser sends `auth_token` automatically.
- For mutating requests (POST/PUT/PATCH/DELETE), the frontend reads `csrf_token` from `document.cookie` and sends it as the `X-CSRF-Token` header.
- `chat.ts` streaming `fetch` calls must include `credentials: "include"` and the `X-CSRF-Token` header.

### Refresh token rule
If auto-refresh is ever added to the frontend, the refresh token MUST be stored in a second HttpOnly cookie — never in `localStorage`, `sessionStorage`, or React state that survives page reload.

### Logout semantics — these are precise and must not be changed
- `POST /api/v1/auth/logout` — clears the `auth_token` and `csrf_token` cookies for the **current browser only**. Does NOT call `logout_all_devices()`. Does NOT invalidate other device sessions. The stateless JWT may remain cryptographically valid server-side for up to 60 minutes after logout (by design — stateless JWT tradeoff).
- `POST /api/v1/auth/logout-all` — clears current browser cookies AND explicitly revokes all `UserSession` refresh sessions across all devices. Use for "sign out everywhere" UX. Access token JWTs on other devices still valid until `exp` (same stateless limitation).

**Do NOT merge these two endpoints.** Normal logout must never silently terminate all device sessions.

### Next.js middleware (`proxy.ts`)
`proxy.ts` checks the `csrf_token` cookie to decide UI routing (redirect to `/login` or allow). This is a **UX routing hint only — not a security gate**. An attacker with a fake `csrf_token` may reach the UI page but cannot make any API calls without a valid `auth_token`. The backend is the real security boundary.
<!-- END:auth-architecture-rules -->
