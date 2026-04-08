### Feature: Implement GET /api/v1/auth/google/login & GET /api/v1/auth/google/callback — Google OAuth 2.0

**Problem**
FluentMeet has no social login option. Requiring all users to register with email and password creates friction, especially for users already authenticated with Google. Without OAuth, FluentMeet also cannot access a user's verified Google email, reducing trust in email authenticity. Implementing Google OAuth requires both a redirect endpoint (to initiate the flow) and a callback endpoint (to handle the code exchange after Google redirects back).

**Proposed Solution**
Implement two endpoints using the **Authorization Code flow**:
1. `GET /api/v1/auth/google/login` — generates a Google OAuth authorization URL with a CSRF `state` parameter and redirects the user to Google's consent screen.
2. `GET /api/v1/auth/google/callback` — receives the authorization code from Google, exchanges it for an access token via `httpx`, fetches the user's profile, and either creates a new account or links the Google identity to an existing one. On success, issues FluentMeet JWT tokens and sets the `HttpOnly` refresh cookie — identical to the `/login` response.

**User Stories**
*   **As a new user,** I want to sign up with my existing Google account, so I can start using FluentMeet without creating and remembering a new password.
*   **As a returning user,** I want to log in with Google and be seamlessly returned to my existing FluentMeet account, so I don't need to remember which method I originally signed up with.
*   **As a security engineer,** I want the OAuth `state` parameter to be validated on callback, so CSRF attacks cannot inject a foreign authorization code into a user's session.

**Acceptance Criteria**
1.  **`GET /api/v1/auth/google/login`**:
    *   Generates a cryptographically random `state` token, stores it in Redis with a 10-minute TTL (`oauth_state:{state}`).
    *   Constructs the Google authorization URL with scopes `openid`, `email`, and `profile`.
    *   Returns an HTTP `302 Redirect` to the Google consent screen URL.

2.  **`GET /api/v1/auth/google/callback?code=<code>&state=<state>`**:
    *   **CSRF validation**: Checks `oauth_state:{state}` in Redis. If not found or mismatched, return `400 Bad Request`:
        ```json
        { "status": "error", "code": "INVALID_OAUTH_STATE", "message": "OAuth state is invalid or has expired.", "details": [] }
        ```
    *   Deletes the `state` key from Redis immediately after validation (single-use).
    *   Exchanges `code` for Google tokens via `POST https://oauth2.googleapis.com/token` using `httpx`.
    *   Fetches the user's Google profile (`email`, `name`, `picture`) from `https://www.googleapis.com/oauth2/v3/userinfo`.
    *   **Account resolution**:
        *   If a user with this email exists: link the Google identity (set `google_id`, `is_verified=True`) and log them in.
        *   If no user exists: create a new `User` record with `is_verified=True`, a random secure `hashed_password` (since no password was set), and the Google profile data.
    *   Issues FluentMeet access + refresh tokens (identical to `/login` response).
    *   Sets the `HttpOnly` refresh token cookie.
    *   Redirects to the frontend with the access token in a short-lived query parameter or fragment: `https://app.fluentmeet.com/oauth-success?access_token=<jwt>`.

3.  Google OAuth credentials (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`) are sourced from environment variables.
4.  If the Google API call fails (network error or invalid code), return `502 Bad Gateway`:
    ```json
    { "status": "error", "code": "OAUTH_PROVIDER_ERROR", "message": "Failed to authenticate with Google. Please try again.", "details": [] }
    ```
5.  Unit and integration tests cover: valid flow (new user, existing user), invalid state, expired state, and Google API failure.

**Proposed Technical Details**
*   **`httpx`**: Already in `requirements.txt` — used for the token exchange and userinfo calls as an async HTTP client.
*   **Google OAuth URLs**:
    *   Authorization: `https://accounts.google.com/o/oauth2/v2/auth`
    *   Token exchange: `https://oauth2.googleapis.com/token`
    *   Userinfo: `https://www.googleapis.com/oauth2/v3/userinfo`
*   **User Model Update**: Add `google_id: Mapped[str | None]` column to `app/models/user.py`; generate an Alembic migration.
*   **Config**: Add `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `FRONTEND_URL` to `app/core/config.py` and `.env.example`.
*   **OAuth Service**: `app/services/oauth_google.py` — encapsulates `build_auth_url`, `exchange_code`, and `get_user_info` functions [NEW].
*   **New/Modified Files**:
    *   `app/api/v1/endpoints/auth.py` — add `GET /google/login`, `GET /google/callback` [MODIFY]
    *   `app/services/oauth_google.py` [NEW]
    *   `app/models/user.py` — add `google_id` column [MODIFY]
    *   `app/core/config.py` — add Google OAuth and frontend URL settings [MODIFY]
    *   Alembic migration for `google_id` column [NEW]

**Tasks**
- [ ] Add `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `FRONTEND_URL` to `app/core/config.py` and `.env.example`.
- [ ] Add `google_id` column to `app/models/user.py` and generate an Alembic migration.
- [ ] Implement `build_auth_url`, `exchange_code`, and `get_user_info` in `app/services/oauth_google.py`.
- [ ] Implement `GET /api/v1/auth/google/login` with `state` generation and Redis storage.
- [ ] Implement `GET /api/v1/auth/google/callback` with CSRF validation, account resolution, token issuance, and cookie setting.
- [ ] Handle Google API failures with `502` using `OAuthProviderException`.
- [ ] Write unit tests for `oauth_google.py` (mock `httpx` calls).
- [ ] Write integration tests: new user signup via Google, existing user login via Google, invalid state, Google API failure.

**Open Questions/Considerations**
*   Should the access token be passed back to the frontend via a URL query parameter (simpler but briefly visible in browser history) or via a short-lived Redis-backed code that the frontend exchanges in a second request (more secure)?
*   If a user originally registered with email/password and then tries to log in with Google using the same email, should they be automatically linked or asked to confirm the link first?
*   Should we support additional OAuth providers (GitHub, Microsoft) from the start, or build the Google integration first and abstract it into a provider pattern in a follow-up issue?
*   What should happen if the Google account does not return an email (some Google accounts have this privacy setting enabled)?
