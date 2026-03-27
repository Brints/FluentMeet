### Feature: Implement POST /api/v1/auth/refresh-token — Token Rotation Endpoint

**Problem**
Access tokens are intentionally short-lived (15 minutes) to limit the damage from theft. Without a token rotation endpoint, users would be forced to re-enter their credentials every 15 minutes, making the application unusable. Additionally, if refresh tokens are never rotated, a stolen refresh token remains valid indefinitely until its fixed expiry — a significant security risk.

**Proposed Solution**
Implement `POST /api/v1/auth/refresh-token` which reads the refresh token from the `HttpOnly` cookie set during login, validates it, issues a brand new access token and refresh token pair, and immediately **revokes the old refresh token's `jti`** in Redis. This implements the **Refresh Token Rotation** pattern: each use of a refresh token produces a new one, and the old one is invalidated, making stolen tokens detectable (reuse of a revoked token is treated as a breach).

**User Stories**
*   **As a logged-in user,** I want my access token to be silently renewed without re-entering my password, so my session stays active without interruption.
*   **As a security engineer,** I want each refresh token to be single-use, so that if a refresh token is stolen and used by an attacker, the server detects the reuse and can invalidate the session.
*   **As a developer,** I want token rotation to be completely transparent to the client — the same cookie is updated — so the frontend requires no special logic beyond retrying a failed request.

**Acceptance Criteria**
1.  `POST /api/v1/auth/refresh-token` reads the refresh token **from the `HttpOnly` cookie** (`refresh_token`), not from the request body.
2.  **Validation**:
    *   If the cookie is absent, return `401 Unauthorized`:
        ```json
        { "status": "error", "code": "MISSING_REFRESH_TOKEN", "message": "No refresh token provided.", "details": [] }
        ```
    *   If the token signature is invalid or expired, return `401 Unauthorized`:
        ```json
        { "status": "error", "code": "INVALID_REFRESH_TOKEN", "message": "Refresh token is invalid or has expired.", "details": [] }
        ```
    *   If the token's `jti` is **not found in Redis** (already revoked), return `401 Unauthorized` and trigger a **full session invalidation** (delete all refresh tokens for this user) to respond to a potential token theft replay attack:
        ```json
        { "status": "error", "code": "REFRESH_TOKEN_REUSE", "message": "Session has been invalidated. Please log in again.", "details": [] }
        ```
3.  **Token Rotation**:
    *   The old refresh token `jti` is deleted from Redis.
    *   A new access token and refresh token pair is generated with fresh `jti` values.
    *   The new refresh token `jti` is stored in Redis with a full TTL reset.
4.  On success, the response is `200 OK`:
    ```json
    {
      "status_code": 200,
      "status": "success",
      "message": "Refresh Token successfully generated"
      "data": {
        "access_token": "<new_jwt>",
        "refresh_token": "<new_jwt>",
        "token_type": "bearer",
        "expires_in": 900
      }
    }
    ```
    The new refresh token is set as a fresh `HttpOnly` cookie (overwriting the previous one):
    ```
    Set-Cookie: refresh_token=<new_jwt>; HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth; Max-Age=604800
    ```
5.  The user's `is_active` and `deleted_at` status are re-checked at rotation time. If the account was deactivated since the last login, the rotation returns `403 Forbidden` with code `ACCOUNT_DEACTIVATED`.
6.  The endpoint is rate-limited to **30 requests/minute** per IP (higher than login since clients call this automatically).
7.  Unit and integration tests cover: valid rotation, missing cookie, expired token, revoked `jti` (reuse detection), and deactivated account.

**Proposed Technical Details**
*   **Router**: `app/api/v1/endpoints/auth.py` — new `POST /refresh-token` route.
*   **Cookie Read**: `request.cookies.get("refresh_token")` inside the route handler.
*   **JWT Decode**: `jose.jwt.decode(token, SECRET_KEY, algorithms=["HS256"])` in `app/core/security.py` — `decode_refresh_token(token) -> TokenData`.
*   **Redis Operations** in `app/services/token_store.py`:
    *   `is_refresh_token_valid(jti) -> bool` — checks key exists.
    *   `revoke_refresh_token(jti)` — deletes the key.
    *   `revoke_all_user_tokens(email)` — scans and deletes all `refresh_token:{jti}` keys for a user (reuse breach response).
*   **Reuse Detection**: On `jti` not found in Redis, call `revoke_all_user_tokens(email)` before returning `401`. This ensures that even if an attacker obtained an old refresh token and used it while the legitimate user was active, the entire session family is torn down.
*   **New/Modified Files**:
    *   `app/api/v1/endpoints/auth.py` — add `POST /refresh-token` [MODIFY]
    *   `app/core/security.py` — add `decode_refresh_token` [MODIFY]
    *   `app/services/token_store.py` — add `is_refresh_token_valid`, `revoke_all_user_tokens` [MODIFY]

**Tasks**
- [ ] Implement `decode_refresh_token` in `app/core/security.py`.
- [ ] Implement `is_refresh_token_valid` and `revoke_all_user_tokens` in `app/services/token_store.py`.
- [ ] Implement `POST /api/v1/auth/refresh-token` in `app/api/v1/endpoints/auth.py`.
- [ ] Add re-check of `is_active` / `deleted_at` on token rotation.
- [ ] Implement reuse detection: revoke all user tokens on stale `jti` usage.
- [ ] Apply `@limiter.limit("30/minute")` rate limit to the refresh route.
- [ ] Write unit tests for `decode_refresh_token`, `is_refresh_token_valid`, and `revoke_all_user_tokens`.
- [ ] Write integration tests: valid rotation, expired token, missing cookie, revoked `jti` (reuse), deactivated account.

**Open Questions/Considerations**
*   `revoke_all_user_tokens` requires scanning Redis by a user email pattern. Should we maintain a Redis **Set** per user (`user_tokens:{email} → Set{jti, ...}`) to make this O(1) instead of a scan?
*   Should token rotation silently succeed if the user's account is active, or should it also extend the cookie `Max-Age` on each rotation (effectively creating a sliding session)?
*   If the client receives a `REFRESH_TOKEN_REUSE` error, should it silently redirect to login or display an explicit "your session was accessed from another location" security warning?
*   Should we implement **refresh token families** (track a root `family_id` across all rotations) to get even more precise reuse detection granularity?
