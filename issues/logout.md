### Feature: Implement POST /api/v1/auth/logout — Session Termination Endpoint

**Problem**
Without a logout endpoint, a user's session can only be terminated by waiting for both the access token and refresh token to expire naturally. This is unacceptable for a secure application — users must be able to explicitly end their session, especially on shared devices. Additionally, simply deleting the cookie client-side is insufficient: the refresh token `jti` remains valid in Redis and the access token remains usable until its expiry.

**Proposed Solution**
Implement `POST /api/v1/auth/logout` which performs a **two-step server-side invalidation**:
1. **Blacklist the Access Token**: The AT's `jti` is written to a Redis blacklist with a TTL equal to its remaining lifetime. The `get_current_user` dependency checks this blacklist on every authenticated request.
2. **Revoke the Refresh Token**: The RT's `jti` is deleted from `refresh_token_store` in Redis, making further token rotations impossible.

Finally, the server clears the `HttpOnly` refresh token cookie by overwriting it with an expired one.

**User Stories**
*   **As a user,** I want to log out and have my session immediately invalidated on the server, so that even if someone intercepts my access token it cannot be used after I log out.
*   **As a user on a shared device,** I want to log out and be confident that no one can resume my session using the refresh token cookie, even before it expires.
*   **As a developer,** I want logout to succeed even if the client sends an expired or missing refresh token, so the user is never stuck in a state where they cannot log out.

**Acceptance Criteria**
1.  `POST /api/v1/auth/logout` requires a valid access token in the `Authorization: Bearer <token>` header.
2.  **Access Token Blacklisting**:
    *   The AT's `jti` is extracted from the token payload.
    *   It is written to Redis as `blacklist:{jti}` with a TTL equal to the token's remaining lifetime in seconds.
    *   From this point, the `get_current_user` dependency rejects this `jti` with `401 Unauthorized` on any subsequent request.
3.  **Refresh Token Revocation**:
    *   The RT `jti` is read from the `HttpOnly` cookie (if present) and deleted from Redis (`refresh_token:{jti}`).
    *   If the cookie is absent or already revoked, logout still succeeds — this case is not treated as an error.
4.  **Cookie Clearance**: The server overwrites the `refresh_token` cookie with an empty value and `Max-Age=0` to instruct the browser to delete it immediately:
    ```
    Set-Cookie: refresh_token=; HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth; Max-Age=0
    ```
5.  On success, the response is `200 OK`:
    ```json
    { "status": "ok", "message": "Successfully logged out." }
    ```
6.  If the access token is expired or invalid, return `401 Unauthorized` — the client should redirect to login.
7.  The endpoint is rate-limited to **20 requests/minute** per IP.
8.  Unit and integration tests cover: successful logout (both tokens revoked), logout with missing RT cookie (AT still blacklisted), and subsequent request with blacklisted AT jti returning `401`.

**Proposed Technical Details**
*   **Router**: `app/api/v1/endpoints/auth.py` — new `POST /logout` route.
*   **Authentication**: The route uses the standard `get_current_user` dependency to validate and decode the AT. The decoded `TokenData` (carrying `jti` and remaining TTL) is passed to the logout logic.
*   **AT Blacklist** in `app/services/token_store.py`:
    *   `blacklist_access_token(jti: str, ttl_seconds: int)` — sets `blacklist:{jti}` with TTL.
    *   `is_access_token_blacklisted(jti: str) -> bool` — checks key existence.
*   **`get_current_user` update** in `app/core/deps.py`:
    *   After decoding a valid JWT, call `is_access_token_blacklisted(jti)`. If `True`, raise `UnauthorizedException(code="TOKEN_REVOKED")`.
*   **Cookie Clear**: `response.delete_cookie("refresh_token", path="/api/v1/auth")` in the route handler.
*   **AT Remaining TTL**: Computed as `token_exp - int(datetime.utcnow().timestamp())` to set the exact Redis TTL, so the blacklist entry self-cleans when the token would have expired anyway.
*   **New/Modified Files**:
    *   `app/api/v1/endpoints/auth.py` — add `POST /logout` [MODIFY]
    *   `app/services/token_store.py` — add `blacklist_access_token`, `is_access_token_blacklisted` [MODIFY]
    *   `app/core/deps.py` — add blacklist check in `get_current_user` [MODIFY]

**Tasks**
- [ ] Implement `blacklist_access_token` and `is_access_token_blacklisted` in `app/services/token_store.py`.
- [ ] Update `get_current_user` in `app/core/deps.py` to check the AT blacklist on every authenticated request.
- [ ] Implement `POST /api/v1/auth/logout` in `app/api/v1/endpoints/auth.py`.
- [ ] Revoke the refresh token `jti` from Redis during logout (gracefully handle missing cookie).
- [ ] Clear the `HttpOnly` cookie by setting `Max-Age=0` in the logout response.
- [ ] Apply `@limiter.limit("20/minute")` rate limit to the logout route.
- [ ] Write unit tests for `blacklist_access_token`, `is_access_token_blacklisted`, and the updated `get_current_user`.
- [ ] Write integration tests: successful logout, logout with no RT cookie, subsequent request with blacklisted AT returning `401`.

**Open Questions/Considerations**
*   Should we support a **"logout from all devices"** variant (e.g., `POST /logout?all=true`) that calls `revoke_all_user_tokens(email)` and blacklists all known ATs for the user?
*   The AT blacklist only covers the remaining `exp` window. If `ACCESS_TOKEN_EXPIRE_MINUTES` is very long (e.g., 60 min), the Redis blacklist entry lives for that full duration. Is this an acceptable trade-off, or should we shorten the AT lifetime?
*   Should the logout endpoint be exposed to unauthenticated clients (no AT required) so that a client with only an expired AT can still clear its refresh token cookie server-side?
