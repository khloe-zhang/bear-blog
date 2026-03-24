# app/db.py
from sqlalchemy import Column, Integer, String, Text, DateTime, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
import datetime

Base = declarative_base()

class QAHistory(Base):
    __tablename__ = "qa_history"
    id = Column(Integer, primary_key=True, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    latency_ms = Column(Float)
    config = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


# SQLite 连接
DATABASE_URL = "sqlite:///./data/ai_history.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 初始化数据库
def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db  # yield 让 FastAPI 在请求结束时继续 finally 块
    finally:
        db.close()
