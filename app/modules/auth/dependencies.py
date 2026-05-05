"""Authentication FastAPI Dependencies module.

Defines all core module injectables avoiding circular imports seamlessly natively.
"""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.security import SecurityService, get_security_service
from app.db.session import get_db
from app.modules.auth.account_lockout import (
    AccountLockoutService,
    get_account_lockout_service,
)
from app.modules.auth.oauth_google import GoogleOAuthService
from app.modules.auth.service import AuthService
from app.modules.auth.token_store import TokenStoreService, get_token_store_service
from app.modules.auth.verification import AuthVerificationService
from app.services.email_producer import EmailProducerService, get_email_producer_service


def get_auth_verification_service(
    db: Session = Depends(get_db),
    email_producer: EmailProducerService = Depends(get_email_producer_service),
) -> AuthVerificationService:
    return AuthVerificationService(db=db, email_producer=email_producer)


def get_auth_service(
    db: Session = Depends(get_db),
    security_service: SecurityService = Depends(get_security_service),
    email_producer: EmailProducerService = Depends(get_email_producer_service),
    auth_verification_service: AuthVerificationService = Depends(
        get_auth_verification_service
    ),
    lockout_svc: AccountLockoutService = Depends(get_account_lockout_service),
    token_store: TokenStoreService = Depends(get_token_store_service),
) -> AuthService:
    return AuthService(
        db=db,
        security_service=security_service,
        email_producer=email_producer,
        auth_verification_service=auth_verification_service,
        lockout_svc=lockout_svc,
        token_store=token_store,
    )


def get_google_oauth_service() -> GoogleOAuthService:
    from app.core.config import settings

    if (
        not settings.GOOGLE_CLIENT_ID
        or not settings.GOOGLE_CLIENT_SECRET
        or not settings.GOOGLE_REDIRECT_URI
    ):
        from app.core.exceptions import InternalServerException

        raise InternalServerException(
            message="Google OAuth is not configured on the server."
        )

    return GoogleOAuthService(
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        redirect_uri=settings.GOOGLE_REDIRECT_URI,
    )
