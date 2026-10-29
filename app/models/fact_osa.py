from sqlalchemy import Column, BigInteger, Date, Integer, String, Numeric
from app.core.database import Base

class FactOsaCheck(Base):
    __tablename__ = "fact_osa_checks"

    id = Column(BigInteger, primary_key=True, index=True)
    submit_date = Column(Date)
    year = Column(Integer)
    week_label = Column(String)
    week_number = Column(Integer)
    country_name = Column(String)
    channel_name = Column(String)
    customer_name = Column(String)
    store_code = Column(String, index=True)
    store_name = Column(String)
    category_name = Column(String)
    sap_code = Column(String)
    sku_name = Column(String)
    barcode = Column(String)
    display_type = Column(String)
    osa_type = Column(String)
    system_user_name = Column(String)
    full_name = Column(String)
    osa_flag = Column(Integer)  # 1 for available, 0 for out of stock
    url = Column(String)