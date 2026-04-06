from fastapi import Depends
from sqlalchemy.orm import Session

from app.auth.account_lockout import AccountLockoutService, get_account_lockout_service
from app.auth.service import AuthService
from app.auth.token_store import TokenStoreService, get_token_store_service
from app.auth.verification import AuthVerificationService
from app.core.security import SecurityService, get_security_service
from app.db.session import get_db
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
    auth_verification_service: AuthVerificationService = Depends(get_auth_verification_service),
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
