import uuid
from sqlalchemy import Column, String, Integer, Boolean, DateTime
from sqlalchemy.sql import func
from app.core.database import Base

class User(Base):
    __tablename__ = "app_users"

    # Use UUID instead of auto-incrementing integer
    user_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    system_user_name = Column(String, nullable=True)
    tier = Column(Integer, nullable=False, default=5)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())