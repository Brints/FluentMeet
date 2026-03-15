from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.crud.user import create_user
from app.db.session import get_db
from app.schemas.auth import SignupResponse
from app.schemas.user import UserCreate

router = APIRouter(prefix="/auth", tags=["auth"])
DB_SESSION_DEPENDENCY = Depends(get_db)


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_201_CREATED,
)
def signup(user_in: UserCreate, db: Session = DB_SESSION_DEPENDENCY) -> SignupResponse:
    user = create_user(db=db, user_in=user_in)
    return SignupResponse.model_validate(user)
