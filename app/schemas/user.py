from pydantic import BaseModel
from typing import Optional

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

class UserResponse(BaseModel):
    user_id: int
    username: str
    tier: int
    is_active: bool

    class Config:
        from_attributes = True

class UserLogin(BaseModel):
    username: str
    password: str

from pydantic import BaseModel, EmailStr
from typing import Optional

class UserCreate(BaseModel):
    username: str
    password: str
    tier: int = 5  # Default to Merchandiser tier
    system_user_name: Optional[str] = None