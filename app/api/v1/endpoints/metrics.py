from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User

router = APIRouter(prefix="/metrics", tags=["Metrics"])

@router.get("/general-stats")
def get_general_stats(
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    return {
        "status": "success",
        "message": f"Welcome {current_user.username}! Your JWT token was successfully verified by FastAPI."
    }