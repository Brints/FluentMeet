### Feature: Implement User Profile Endpoints — GET, PATCH & DELETE /api/v1/users/me

**Problem**
Authenticated users have no way to view their own profile, update their display name or language preferences, upload an avatar, or delete their account. Without these endpoints, the platform cannot support any personalisation or account management beyond initial registration. Account deletion is also a legal requirement (GDPR Right to Erasure) and must support both a grace-period soft delete and a permanent hard delete.

**Proposed Solution**
Implement three endpoints under `/api/v1/users/me`, all protected by the `get_current_user` dependency:

- `GET /me` — returns the authenticated user's full profile.
- `PATCH /me` — allows partial updates to display name, language preferences, and avatar.
- `DELETE /me` — soft-deletes the account by default, with a `?hard=true` query parameter for permanent deletion.

**User Stories**
*   **As a logged-in user,** I want to retrieve my profile details, so I can verify my current settings and display them in the UI.
*   **As a user,** I want to update my display name, speaking language, and listening language without re-authenticating, so I can personalise my experience at any time.
*   **As a user,** I want to upload a profile picture that is visible to other meeting participants, so they can identify me during calls.
*   **As a user who wants to leave the platform,** I want to delete my account and have my personal data removed, so my data is not retained longer than I consent to.

---

### GET /api/v1/users/me — Get Current User Profile

**Acceptance Criteria**
1.  Requires a valid `Authorization: Bearer <access_token>` header.
2.  Returns `200 OK` with the authenticated user's public profile:
    ```json
    {
        "status_code": 200,
        "status": "success",
        "message": "User profile retrieved successfully.",
        "data": {
            "id": "<uuid>",
            "email": "user@example.com",
            "full_name": "Ada Lovelace",
            "avatar_url": "https://res.cloudinary.com/fluentmeet/...",
            "speaking_language": "en",
            "listening_language": "fr",
            "is_active": true,
            "is_verified": true,
            "created_at": "2026-03-14T12:00:00Z"
        }
    }
    ```
3.  `hashed_password`, `deleted_at`, and other internal fields are **never** returned.

---

### PATCH /api/v1/users/me — Update Profile

**Acceptance Criteria**
1.  Requires a valid `Authorization: Bearer <access_token>` header.
2.  Accepts `application/json` for text fields **or** `multipart/form-data` when an avatar file is included. All fields are optional (partial update):
    ```json
    {
        "status_code": 200,
        "status": "success",
        "message": "User profile updated successfully.",
        "data": {
            "full_name": "Ada K. Lovelace",
            "speaking_language": "en",
            "listening_language": "de"
        }
    }
    ```
3.  **Avatar upload** (when provided as `multipart/form-data`):
    *   File must be JPEG, PNG, or WebP; max 5 MB.
    *   Uploaded via `StorageService` (see [External Services issue](./external_service.md)).
    *   The returned public URL is stored in `user.avatar_url`.
    *   The **old avatar is deleted** from cloud storage before setting the new URL.
    *   If no new avatar is provided, the existing `avatar_url` is unchanged.
4.  `speaking_language` and `listening_language` must be valid BCP-47 language codes; invalid values return `400 Bad Request` with code `INVALID_LANGUAGE_CODE`.
5.  Only the fields provided in the request body are updated (true partial update — `PATCH` semantics).
6.  Returns `200 OK` with the updated user profile (same schema as `GET /me`).

---

### DELETE /api/v1/users/me — Account Deletion

**Acceptance Criteria**
1.  Requires a valid `Authorization: Bearer <access_token>` header.
2.  Accepts an optional `?hard=true` query parameter to distinguish between:
    *   **Soft delete** (default, `?hard=false` or omitted): Sets `user.deleted_at = now()` and `user.is_active = False`. The account record is retained in the database.
    *   **Hard delete** (`?hard=true`): Permanently deletes the `User` record and all associated data (verification tokens, reset tokens, room participations) from the database.
3.  In both cases, after the DB operation:
    *   `revoke_all_user_tokens(email)` is called to invalidate all active refresh tokens.
    *   The `HttpOnly` refresh token cookie is cleared (`Max-Age=0`).
    *   The current access token `jti` is blacklisted in Redis.
4.  For **soft delete**, any subsequent `/login` attempt returns `403 Forbidden` with code `ACCOUNT_DELETED` (already enforced in the login endpoint).
5.  For **hard delete**, the user's avatar is deleted from cloud storage as part of the cleanup.
6.  Returns `200 OK` on success:
    ```json
    { "status": "ok", "message": "Account has been successfully deleted." }
    ```
7.  A soft-deleted account cannot be restored via the API — restoration requires a database admin operation.

---

**Proposed Technical Details**
*   **Router**: `app/user/router.py` [NEW] — all three routes registered under an `APIRouter(prefix="/users", tags=["users"])`.
*   **Schemas** in `app/user/schemas.py`:
    *   `UserResponse` — already exists; add `avatar_url: str | None`.
    *   `UserUpdate(BaseModel)` — `full_name: str | None`, `speaking_language: str | None`, `listening_language: str | None` (all optional).
*   **CRUD** in `app/user/service.py`:
    *   `get_user_by_id(db, user_id) -> User | None`
    *   `update_user(db, user, update_data: UserUpdate) -> User`
    *   `soft_delete_user(db, user) -> None`
    *   `hard_delete_user(db, user) -> None`
*   **Avatar handling**: `StorageService` dependency injected into `PATCH /me`; old avatar deleted before uploading new one.
*   **Session teardown on DELETE**: Reuses `blacklist_access_token`, `revoke_all_user_tokens`, and cookie clearing (same pattern as `/logout`).
*   **New/Modified Files**:
    *   `app/api/v1/endpoints/users.py` [NEW]
    *   `app/schemas/user.py` — add `avatar_url` to `UserResponse`, add `UserUpdate` [MODIFY]
    *   `app/crud/user.py` — add update and delete CRUD functions [MODIFY]
    *   `app/api/v1/api.py` — register users router [MODIFY]

**Tasks**
- [ ] Add `avatar_url` to `UserResponse` in `app/schemas/user.py`.
- [ ] Implement `UserUpdate` schema in `app/schemas/user.py`.
- [ ] Implement `update_user`, `soft_delete_user`, and `hard_delete_user` in `app/crud/user.py`.
- [ ] Implement `GET /api/v1/users/me` in `app/api/v1/endpoints/users.py`.
- [ ] Implement `PATCH /api/v1/users/me` with JSON and `multipart/form-data` support, avatar upload, and old avatar cleanup.
- [ ] Implement `DELETE /api/v1/users/me` with soft/hard delete logic, full session teardown, and avatar deletion on hard delete.
- [ ] Register the users router in `app/api/v1/api.py`.
- [ ] Write unit tests for all CRUD functions.
- [ ] Write integration tests for `GET /me`, `PATCH /me` (text update, avatar upload), and `DELETE /me` (soft and hard).

**Open Questions/Considerations**
*   Should soft-deleted accounts have a grace period (e.g., 30 days) during which they can be reactivated by the user via a support request, or is soft-delete a permanent, admin-only reversal?
*   For GDPR Right to Erasure, does hard-delete need to cascade to anonymise the user's data in meeting transcription logs and caption history, or is physical deletion of the `User` row sufficient?
*   Should `PATCH /me` accept both `application/json` (no avatar) and `multipart/form-data` (with avatar) in a single endpoint, or should avatar upload be a separate `POST /me/avatar` endpoint for cleaner API design?
