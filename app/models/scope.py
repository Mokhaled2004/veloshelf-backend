from sqlalchemy import Column, String, ForeignKey
from app.core.database import Base

class UserCountryScope(Base):
    __tablename__ = "sec_user_country_scope"
    user_id = Column(String, ForeignKey("app_users.user_id", ondelete="CASCADE"), primary_key=True)
    country_name = Column(String, primary_key=True)

class UserRegionScope(Base):
    __tablename__ = "sec_user_region_scope"
    user_id = Column(String, ForeignKey("app_users.user_id", ondelete="CASCADE"), primary_key=True)
    region_name = Column(String, primary_key=True)

class UserAccountScope(Base):
    __tablename__ = "sec_user_account_scope"
    user_id = Column(String, ForeignKey("app_users.user_id", ondelete="CASCADE"), primary_key=True)
    account_name = Column(String, primary_key=True)

class UserRouteScope(Base):
    __tablename__ = "sec_user_route_scope"
    user_id = Column(String, ForeignKey("app_users.user_id", ondelete="CASCADE"), primary_key=True)
    route_code = Column(String, primary_key=True)

class UserStoreScope(Base):
    __tablename__ = "sec_user_store_scope"
    user_id = Column(String, ForeignKey("app_users.user_id", ondelete="CASCADE"), primary_key=True)
    store_code = Column(String, primary_key=True)