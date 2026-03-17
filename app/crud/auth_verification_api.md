# Email Verification API

This document describes the email verification endpoints in `app/api/v1/endpoints/auth.py`.

## 1) Verify email

- **Method**: `GET`
- **Path**: `/api/v1/auth/verify-email`
- **Auth required**: No
- **Query params**:
  - `token` (string UUID)

### Success response

```json
{
  "status": "ok",
  "message": "Email successfully verified. You can now log in."
}
```

### Error responses

- Missing token (`400`)

```json
{
  "status": "error",
  "code": "MISSING_TOKEN",
  "message": "Verification token is required.",
  "details": []
}
```

- Invalid token (`400`)

```json
{
  "status": "error",
  "code": "INVALID_TOKEN",
  "message": "Verification token is invalid.",
  "details": []
}
```

- Expired token (`400`)

```json
{
  "status": "error",
  "code": "TOKEN_EXPIRED",
  "message": "Verification token has expired. Please request a new one.",
  "details": []
}
```

## 2) Resend verification

- **Method**: `POST`
- **Path**: `/api/v1/auth/resend-verification`
- **Auth required**: No
- **Rate limit**: `3/minute` per IP
- **Request body**:

```json
{
  "email": "user@example.com"
}
```

### Response (`200` for both existing and non-existing emails)

```json
{
  "message": "If an account with that email exists, we have sent a verification email."
}
```

## Notes

- Signup creates a verification token and queues the verification email through Kafka topic `notifications.email`.
- Verification tokens are single-use: successful verification deletes the token.
- Already verified users are handled idempotently by `GET /verify-email` and receive `200`.
