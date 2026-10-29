from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import get_password_hash
from app.models.user import User
from app.schemas.user import UserCreate, UserResponse
from app.api.deps import get_current_user

router = APIRouter(prefix="/users", tags=["Users"])

@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    user_in: UserCreate, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Optional: ensure only Tier 1 Admin can create users
    if current_user.tier != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Tier-1 Admin users can create new accounts."
        )

    # Check if user already exists
    existing_user = db.query(User).filter(User.username == user_in.username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )

    # Create new user with hashed password
    hashed_password = get_password_hash(user_in.password)
    db_user = User(
        username=user_in.username,
        password_hash=hashed_password,
        tier=user_in.tier,
        system_user_name=user_in.system_user_name,
        is_active=True
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user