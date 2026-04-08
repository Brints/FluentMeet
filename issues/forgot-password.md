### Feature: Implement POST /api/v1/auth/forgot-password — Password Reset Request Endpoint

**Problem**
Users who forget their password have no way to recover their account. Without a forgot-password endpoint, the only recourse is manual admin intervention. Additionally, the endpoint must be carefully designed to avoid leaking whether a given email address is registered — responding differently for known vs. unknown emails is a user enumeration vulnerability.

**Proposed Solution**
Implement `POST /api/v1/auth/forgot-password` which accepts an email address, and if an active verified account exists, generates a time-limited password reset token and dispatches a reset link via the Kafka email pipeline. The endpoint always returns the same success response regardless of whether the email is registered, preventing enumeration.

**User Stories**
*   **As a user who has forgotten their password,** I want to enter my email and receive a reset link, so I can regain access to my account without contacting support.
*   **As a security engineer,** I want the endpoint to return the same response whether or not the email exists, so an attacker cannot use it to discover which email addresses are registered.
*   **As a security engineer,** I want password reset tokens to be time-limited and single-use, so that a leaked reset link cannot be used after expiry or after the password has already been reset.

**Acceptance Criteria**
1.  `POST /api/v1/auth/forgot-password` accepts the following JSON body:
    ```json
    { "email": "user@example.com" }
    ```
2.  **Always returns `200 OK`** with the same response body, regardless of whether the email is registered, verified, or deleted:
    ```json
    { "status": "ok", "message": "If an account with this email exists, a password reset link has been sent." }
    ```
3.  **Internal logic** (invisible to the caller):
    *   If no active, verified user exists with the given email → do nothing and return `200`.
    *   If a valid (unexpired) `PasswordResetToken` already exists for the user → delete it and generate a fresh one (to prevent accumulation of valid reset tokens).
    *   Generate a cryptographically secure `PasswordResetToken` (UUID) with `expires_at = now() + PASSWORD_RESET_TOKEN_EXPIRE_MINUTES` (default: **60 minutes**).
    *   Persist the token to the `password_reset_tokens` table.
    *   Publish to the `notifications.email` Kafka topic:
        ```json
        {
          "to": "user@example.com",
          "subject": "Reset your FluentMeet password",
          "template": "password_reset",
          "data": { "full_name": "Ada Lovelace", "reset_link": "https://...", "expires_in_minutes": 60 }
        }
        ```
4.  The reset link format: `https://app.fluentmeet.com/reset-password?token=<uuid>` (the frontend routes the user to the form, which calls `POST /reset-password`).
5.  The endpoint is rate-limited to **5 requests/minute** per IP to prevent email flooding.
6.  Kafka publish failure must **not** cause the endpoint to return an error — the token is still saved and a retry mechanism handles the email delivery.
7.  Unit and integration tests cover: registered email (token created + email published), unknown email (no side effects), existing unexpired token (old token replaced), and rate limit enforcement.

**Proposed Technical Details**
*   **Router**: `app/api/v1/endpoints/auth.py` — new `POST /forgot-password` route.
*   **Token Model**: `PasswordResetToken` — new SQLAlchemy model in `app/models/password_reset_token.py`:
    *   `id`, `user_id` (FK → `users`), `token` (UUID, unique, indexed), `expires_at`, `created_at`.
*   **CRUD** in `app/crud/password_reset_token.py`:
    *   `create_token(db, user_id) -> PasswordResetToken`
    *   `delete_existing_tokens(db, user_id) -> None` — deletes all prior tokens for the user before creating a new one.
    *   `get_token(db, token: str) -> PasswordResetToken | None`
*   **Config**: Add `PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 60` to `app/core/config.py`.
*   **Email Trigger**: `EmailProducerService.send_email(...)` called after token creation, using the `password_reset` template.
*   **New/Modified Files**:
    *   `app/api/v1/endpoints/auth.py` — add `POST /forgot-password` [MODIFY]
    *   `app/models/password_reset_token.py` [NEW]
    *   `app/crud/password_reset_token.py` [NEW]
    *   `app/core/config.py` — add `PASSWORD_RESET_TOKEN_EXPIRE_MINUTES` [MODIFY]
    *   Alembic migration for `password_reset_tokens` table [NEW]

**Tasks**
- [ ] Implement `PasswordResetToken` SQLAlchemy model in `app/models/password_reset_token.py`.
- [ ] Generate and apply an Alembic migration for `password_reset_tokens`.
- [ ] Implement `create_token`, `delete_existing_tokens`, and `get_token` in `app/crud/password_reset_token.py`.
- [ ] Add `PASSWORD_RESET_TOKEN_EXPIRE_MINUTES` to `app/core/config.py` and `.env.example`.
- [ ] Implement `POST /api/v1/auth/forgot-password` with enumeration-safe response.
- [ ] Integrate `EmailProducerService` to publish the password reset email (non-blocking on Kafka failure).
- [ ] Apply `@limiter.limit("5/minute")` to the route.
- [ ] Write unit tests for `create_token` and `delete_existing_tokens` CRUD.
- [ ] Write integration tests: registered email, unknown email, existing token replaced, rate limit.

**Open Questions/Considerations**
*   Should the reset link point directly to the backend (`GET /api/v1/auth/reset-password?token=...`) and redirect to the frontend, or point directly to the frontend URL and let the frontend call `POST /reset-password`? The latter is cleaner for SPAs.
*   Should we delete the `PasswordResetToken` immediately after the email is published, or keep it in the database until it is used or expires? Keeping it allows checking expiry in `POST /reset-password`.
*   Should we notify the user via email if a password reset is requested for their account but they did not initiate it (a security notification)?
*   Should we add a `last_password_reset_requested_at` column to the `users` table to enforce a minimum cooldown between requests per user, in addition to the IP rate limit?
