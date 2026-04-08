### Feature: Implement POST /api/v1/auth/change-password — Authenticated Password Update Endpoint

**Problem**
Authenticated users have no way to update their password voluntarily (e.g., routine credential rotation or after suspecting their password was exposed). The `/reset-password` flow exists for forgotten passwords but requires a reset email — it is not suitable for users who know their current password and simply want to change it. A dedicated change-password endpoint should require proof of the current password before accepting a new one.

**Proposed Solution**
Implement `POST /api/v1/auth/change-password` as a protected endpoint that requires a valid access token. It verifies the user's current password before accepting the new one, updates the hash in the database, and revokes all other active refresh tokens to force re-login on other devices — giving the user confidence that only their current session remains active.

**User Stories**
*   **As a logged-in user,** I want to change my password by providing my current password and a new one, so I can rotate my credentials without going through a full reset flow.
*   **As a security-conscious user,** I want all my other active sessions to be terminated when I change my password, so I know no stale sessions remain after the update.
*   **As a security engineer,** I want the current password to be verified before any update, so an attacker who gains brief access to an authenticated session cannot silently change the password.

**Acceptance Criteria**
1.  `POST /api/v1/auth/change-password` requires a valid `Authorization: Bearer <access_token>` header.
2.  Accepts the following JSON body:
    ```json
    {
      "current_password": "OldP@ssw0rd!",
      "new_password": "NewP@ssw0rd!"
    }
    ```
3.  **Validation**:
    *   `new_password` — minimum 8 characters.
    *   If `current_password` does not match the stored hash, return `400 Bad Request`:
        ```json
        { "status": "error", "code": "INCORRECT_PASSWORD", "message": "Current password is incorrect.", "details": [] }
        ```
    *   If `new_password` is identical to `current_password`, return `400 Bad Request`:
        ```json
        { "status": "error", "code": "SAME_PASSWORD", "message": "New password must be different from the current password.", "details": [] }
        ```
4.  On valid input, in a single atomic transaction:
    *   Hash `new_password` with bcrypt.
    *   Update `user.hashed_password` and `user.updated_at = now()`.
5.  After the DB commit, call `revoke_all_user_tokens(email)` to invalidate all active refresh tokens across all devices.
6.  On success, return `200 OK`:
    ```json
    { "status": "ok", "message": "Password updated successfully." }
    ```
7.  The current session's access token remains valid until its natural expiry (`ACCESS_TOKEN_EXPIRE_MINUTES`). Only refresh tokens are revoked — so the user's current request continues to work, but they will need to log in again on next refresh.
8.  The endpoint is rate-limited to **10 requests/minute** per authenticated user.
9.  Unit and integration tests cover: successful change, wrong current password, same password rejection, and session revocation.

**Proposed Technical Details**
*   **Router**: `app/api/v1/endpoints/auth.py` — new `POST /change-password` route.
*   **Auth**: Uses `get_current_user` dependency; the route receives the currently authenticated `User` object.
*   **Schema**: New `ChangePasswordRequest(current_password: str, new_password: str = Field(..., min_length=8))` in `app/schemas/auth.py`.
*   **Reuses**: `verify_password` from `app/core/security.py`, `get_password_hash` from `app/core/security.py`, and `revoke_all_user_tokens` from `app/services/token_store.py`.
*   **New/Modified Files**:
    *   `app/api/v1/endpoints/auth.py` — add `POST /change-password` [MODIFY]
    *   `app/schemas/auth.py` — add `ChangePasswordRequest` [MODIFY]

**Tasks**
- [ ] Add `ChangePasswordRequest` schema to `app/schemas/auth.py`.
- [ ] Implement `POST /api/v1/auth/change-password` in `app/api/v1/endpoints/auth.py`.
- [ ] Verify current password using `verify_password` before accepting the new one.
- [ ] Reject new password if identical to current password.
- [ ] Hash and persist the new password within an atomic DB transaction.
- [ ] Call `revoke_all_user_tokens(email)` after DB commit.
- [ ] Apply `@limiter.limit("10/minute")` to the route.
- [ ] Write unit tests: wrong current password, same password, successful change.
- [ ] Write integration tests: full flow including session revocation check.

**Open Questions/Considerations**
*   Should a confirmation email be sent to the user notifying them that their password was changed (security notification)?
*   Should we also blacklist the current access token `jti` on password change to force re-login on the current device immediately, or keep it valid until natural expiry for a smoother UX?
*   Should we enforce a password history policy (e.g., cannot reuse the last 3 passwords)? This requires storing previous hashed passwords.
