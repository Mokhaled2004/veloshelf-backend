from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import verify_password, create_access_token
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["Authentication"])

class LoginRequest(BaseModel):
    username: str
    password: str

@router.post("/login")
def login(credentials: LoginRequest, db: Session = Depends(get_db)):
    # 1. Look up user by username in the database
    user = db.query(User).filter(User.username == credentials.username).first()
    
    # 2. Verify password securely
    if not user or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    
    # 3. Embed database-assigned tier & user_id into the tamper-proof JWT token
    access_token = create_access_token(
        data={
            "sub": user.username,
            "tier": user.tier,
            "user_id": user.user_id
        }
    )
    
    # Return token and basic metadata (frontend can read username for display safely)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "username": user.username,
        "tier": user.tier
    }