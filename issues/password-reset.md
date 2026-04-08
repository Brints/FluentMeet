### Feature: Implement POST /api/v1/auth/reset-password — Password Reset Endpoint

**Problem**
After a user requests a password reset and receives the reset link via email, there is no endpoint to process the new password. Without this, the forgot-password flow is incomplete — users can receive the link but have no way to use it. Additionally, resetting the password must invalidate all existing sessions to ensure that whoever triggered the account compromise can no longer access it.

**Proposed Solution**
Implement `POST /api/v1/auth/reset-password` which accepts a reset token (from the email link) and a new password, validates the token, hashes and persists the new password, deletes the token to prevent reuse, and revokes all active refresh tokens for the user. This ensures a clean slate after a password reset regardless of how many devices were previously logged in.

**User Stories**
*   **As a user who received a reset link,** I want to submit a new password and have it take effect immediately, so I can log back in and regain full access to my account.
*   **As a user,** I want all my other active sessions to be terminated when I reset my password, so that whoever may have had unauthorised access is immediately locked out.
*   **As a security engineer,** I want the reset token to be deleted immediately after use, so that the same reset link cannot be used again if intercepted.

**Acceptance Criteria**
1.  `POST /api/v1/auth/reset-password` accepts the following JSON body:
    ```json
    {
      "token": "<uuid>",
      "new_password": "MyNewStr0ng@Pass!"
    }
    ```
2.  **Input Validation**:
    *   `token` — required, non-empty string.
    *   `new_password` — required, minimum 8 characters (same rules as `/signup`).
3.  **Token Validation**:
    *   If no matching `PasswordResetToken` is found, return `400 Bad Request`:
        ```json
        { "status": "error", "code": "INVALID_RESET_TOKEN", "message": "Password reset token is invalid.", "details": [] }
        ```
    *   If the token exists but `expires_at < now()`, return `400 Bad Request`:
        ```json
        { "status": "error", "code": "RESET_TOKEN_EXPIRED", "message": "Password reset token has expired. Please request a new one.", "details": [] }
        ```
4.  **On Valid Token** (executed as a single atomic transaction):
    *   Hash the `new_password` using bcrypt.
    *   Update `user.hashed_password` with the new hash and `user.updated_at = now()`.
    *   Delete the `PasswordResetToken` record from the database.
    *   Call `revoke_all_user_tokens(email)` from `app/services/token_store.py` to delete all refresh token `jti` entries from Redis, invalidating all active sessions.
5.  On success, return `200 OK`:
    ```json
    { "status": "ok", "message": "Password has been reset successfully. Please log in with your new password." }
    ```
6.  The endpoint does **not** automatically issue new tokens or log the user in — they must go through `/login` with the new password.
7.  The endpoint is rate-limited to **5 requests/minute** per IP.
8.  Unit and integration tests cover: valid reset, invalid token, expired token, and full session revocation after reset.

**Proposed Technical Details**
*   **Router**: `app/api/v1/endpoints/auth.py` — new `POST /reset-password` route.
*   **Schema**: New `ResetPasswordRequest(token: str, new_password: str = Field(..., min_length=8))` in `app/schemas/auth.py`.
*   **CRUD**: Reuses `get_token` and `delete_token` from `app/crud/password_reset_token.py` (created in the [Forgot Password issue](./auth_forgot_password.md)).
*   **Session Revocation**: `revoke_all_user_tokens(email)` from `app/services/token_store.py` (created in the [Refresh Token issue](./auth_refresh_token.md)).
*   **Atomic Transaction**: `user.hashed_password` update, token deletion, and Redis revocation are sequenced such that the DB transaction commits first, then Redis keys are removed. If the DB commit fails, nothing changes.
*   **New/Modified Files**:
    *   `app/api/v1/endpoints/auth.py` — add `POST /reset-password` [MODIFY]
    *   `app/schemas/auth.py` — add `ResetPasswordRequest` [MODIFY]

**Tasks**
- [ ] Add `ResetPasswordRequest` Pydantic schema to `app/schemas/auth.py`.
- [ ] Implement `POST /api/v1/auth/reset-password` in `app/api/v1/endpoints/auth.py`.
- [ ] Reuse `get_token` and `delete_token` from `app/crud/password_reset_token.py`.
- [ ] Hash the new password and update `user.hashed_password` within a DB transaction.
- [ ] Call `revoke_all_user_tokens(email)` after successful DB commit to invalidate all sessions.
- [ ] Apply `@limiter.limit("5/minute")` to the route.
- [ ] Write unit tests for token validation (invalid, expired) and password update logic.
- [ ] Write integration tests: valid reset (password updated + sessions revoked), invalid token, expired token.

**Open Questions/Considerations**
*   Should we send a confirmation email to the user after a successful password reset (e.g., "Your password was changed — if this wasn't you, contact support")? This is a standard security notification.
*   Should the new password be rejected if it is the same as the current password? This requires comparing the new hash against `user.hashed_password`, which requires a `verify_password` check before updating.
*   If `revoke_all_user_tokens` fails (Redis is temporarily unavailable), should the password reset succeed anyway (prioritising account recovery) or roll back (prioritising session security)?
