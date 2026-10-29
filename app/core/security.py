from datetime import datetime, timedelta
from jose import jwt
import bcrypt

SECRET_KEY = "YOUR_SUPER_SECRET_KEY_HERE"  
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440  # 24 hours (1440 minutes)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    # Encode strings to bytes and verify using native bcrypt
    return bcrypt.checkpw(
        plain_password.encode("utf-8"), 
        hashed_password.encode("utf-8")
    )

def get_password_hash(password: str) -> str:
    # Generate salt and hash the password natively
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode("utf-8")

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt