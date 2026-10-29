from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import SECRET_KEY, ALGORITHM
from app.models.user import User
from app.models.scope import (
    UserCountryScope, UserRegionScope, UserAccountScope, UserRouteScope, UserStoreScope
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    return user

class UserContext:
    def __init__(self, user: User, db: Session):
        self.user = user
        self.tier = user.tier
        self.is_unrestricted = (user.tier == 1) # Tier 1 (GM) sees everything[cite: 13]
        
        # Pull explicit scope restrictions from database scope tables
        self.countries = [s.country_name for s in db.query(UserCountryScope).filter_by(user_id=user.user_id).all()]
        self.regions = [s.region_name for s in db.query(UserRegionScope).filter_by(user_id=user.user_id).all()]
        self.accounts = [s.account_name for s in db.query(UserAccountScope).filter_by(user_id=user.user_id).all()]
        self.routes = [s.route_code for s in db.query(UserRouteScope).filter_by(user_id=user.user_id).all()]
        self.stores = [s.store_code for s in db.query(UserStoreScope).filter_by(user_id=user.user_id).all()]

def get_user_context(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UserContext:
    return UserContext(current_user, db)

def require_minimum_tier(required_tier: int):
    def role_dependency(context: UserContext = Depends(get_user_context)):
        if context.tier > required_tier:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have sufficient permissions to access this feature."
            )
        return context
    return role_dependency