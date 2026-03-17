### Feature: Implement GET /api/v1/auth/verify-email — Email Verification Endpoint

**Problem**
After signup, new user accounts are created with `is_verified=False`. Without an email verification endpoint, there is no way for users to activate their accounts, and the `is_verified` flag serves no purpose. Unverified users are blocked from logging in (enforced in the `/login` endpoint), creating a dead end if the verification link cannot be processed.

**Proposed Solution**
Implement `GET /api/v1/auth/verify-email?token=<uuid>` which looks up the verification token in the database, checks it is valid and unexpired, marks the user as verified (`is_verified=True`), and invalidates the token to prevent reuse. Since this endpoint is accessed by clicking a link in an email, it must be a `GET` request with the token as a query parameter.

**User Stories**
*   **As a new user,** I want to click the link in my verification email and have my account immediately activated, so I can log in without any further steps.
*   **As a new user,** I want to see a clear error if my verification link has expired, with guidance on how to request a new one, so I am not left confused with an inactive account.
*   **As a security engineer,** I want each verification token to be single-use and time-limited, so that a leaked or intercepted verification link cannot be used to verify an account it was not sent to.

**Acceptance Criteria**
1.  `GET /api/v1/auth/verify-email?token=<uuid>` is a public endpoint (no authentication required).
2.  **Token Lookup & Validation**:
    *   If the `token` query parameter is absent, return `400 Bad Request`:
        ```json
        { "status": "error", "code": "MISSING_TOKEN", "message": "Verification token is required.", "details": [] }
        ```
    *   If no matching `VerificationToken` record is found, return `400 Bad Request`:
        ```json
        { "status": "error", "code": "INVALID_TOKEN", "message": "Verification token is invalid.", "details": [] }
        ```
    *   If the token exists but `expires_at < now()`, return `400 Bad Request`:
        ```json
        { "status": "error", "code": "TOKEN_EXPIRED", "message": "Verification token has expired. Please request a new one.", "details": [] }
        ```
    *   If the token's associated user is already verified (`is_verified=True`), return `200 OK` idempotently — do not treat this as an error.
3.  **On Valid Token**:
    *   Set `user.is_verified = True` and `user.updated_at = now()` in the database.
    *   Delete the `VerificationToken` record to prevent reuse.
    *   Both operations are performed in a single atomic database transaction.
4.  On success, return `200 OK`:
    ```json
    { "status": "ok", "message": "Email successfully verified. You can now log in." }
    ```
5.  A **resend verification** endpoint (`POST /api/v1/auth/resend-verification`) is implemented alongside this one, allowing users with expired tokens to request a new verification email. It:
    *   Accepts `{ "email": "user@example.com" }`.
    *   Deletes any existing unexpired token for the user before generating a new one.
    *   Is rate-limited to **3 requests/minute** per IP to prevent email flooding.
    *   Always returns `200 OK` regardless of whether the email exists, to prevent user enumeration.
6.  Unit and integration tests cover: valid token, invalid token, expired token, already-verified user (idempotent), and resend flow.

**Proposed Technical Details**
*   **Router**: `app/api/v1/endpoints/auth.py` — new `GET /verify-email` and `POST /resend-verification` routes.
*   **Token Model**: `VerificationToken` (created in the [auth_signup issue](./auth_signup.md)) — fields: `id`, `user_id` (FK), `token` (UUID, unique, indexed), `expires_at` (default: `now() + 24h`), `created_at`.
*   **CRUD** in `app/crud/verification_token.py`:
    *   `get_token(db, token: str) -> VerificationToken | None`
    *   `delete_token(db, token_id: int) -> None`
    *   `create_token(db, user_id: int) -> VerificationToken`
*   **Email Trigger for Resend**: Publishes to `notifications.email` Kafka topic (same as signup) with `template: "verification"`.
*   **Atomic Transaction**: `user.is_verified = True` and `delete_token` are wrapped in a single `db.begin()` / `db.commit()` block to ensure consistency if either fails.
*   **New/Modified Files**:
    *   `app/api/v1/endpoints/auth.py` — add `GET /verify-email`, `POST /resend-verification` [MODIFY]
    *   `app/crud/verification_token.py` — token CRUD operations [NEW]

**Tasks**
- [ ] Implement `get_token`, `delete_token`, and `create_token` in `app/crud/verification_token.py`.
- [ ] Implement `GET /api/v1/auth/verify-email` in `app/api/v1/endpoints/auth.py`.
- [ ] Ensure `user.is_verified = True` and token deletion are wrapped in a single atomic transaction.
- [ ] Handle already-verified user idempotently (return `200` without error).
- [ ] Implement `POST /api/v1/auth/resend-verification` with email enumeration protection.
- [ ] Apply `@limiter.limit("3/minute")` to the resend endpoint.
- [ ] Integrate `EmailProducerService` in the resend flow to publish to `notifications.email`.
- [ ] Write unit tests for all `verification_token` CRUD functions.
- [ ] Write integration tests: valid token, invalid token, expired token, already verified (idempotent), and resend flow.

**Open Questions/Considerations**
*   Should a successfully verified user be automatically logged in and receive tokens in the `/verify-email` response, or should they be redirected to the login page to authenticate separately?
*   Should the verification link redirect to a frontend URL (e.g., `https://app.fluentmeet.com/verified`) rather than returning JSON, since this endpoint is opened in a browser?
*   Should the verification token expiry be configurable via settings (`VERIFICATION_TOKEN_EXPIRE_HOURS`), or fixed at 24 hours?
*   If the user never verifies their email, should we schedule an automatic cleanup job to purge unverified accounts older than a threshold (e.g., 7 days)?
