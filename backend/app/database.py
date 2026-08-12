import os
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

os.makedirs(os.path.dirname(settings.DB_PATH) or ".", exist_ok=True)
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)

engine = create_engine(f"sqlite:///{settings.DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class VerifyJob(Base):
    __tablename__ = "verify_jobs"

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String, default="image")  # image | news
    raw_before = Column(Text, default="")   # original image name / news query
    result = Column(Text, default="")       # JSON payload
    created_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()