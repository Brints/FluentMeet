import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.constants import UserRole
from app.auth.models import User
from app.core.config import settings
from app.core.security import security_service

logger = logging.getLogger(__name__)


def init_admin(db: Session) -> None:
    if not settings.ADMIN_EMAIL or not settings.ADMIN_PASSWORD:
        logger.info(
            "Admin credentials not fully set in .env, skipping admin initialization."
        )
        return

    admin_email = settings.ADMIN_EMAIL.lower()

    stmt = select(User).where(User.email == admin_email)
    existing_admin = db.execute(stmt).scalar_one_or_none()

    if existing_admin:
        if existing_admin.user_role != UserRole.ADMIN.value:
            existing_admin.user_role = UserRole.ADMIN.value
            db.commit()
            logger.info("Existing admin user updated with ADMIN role.")
        return

    logger.info("Creating default admin user: System Admin")

    admin_user = User(
        email=admin_email,
        full_name="System Admin",
        hashed_password=security_service.hash_password(settings.ADMIN_PASSWORD),
        user_role=UserRole.ADMIN.value,
        is_active=True,
        is_verified=True,
    )
    db.add(admin_user)
    db.commit()
    logger.info("Default admin user created successfully.")
