import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .models import Base

URL = os.environ.get("CALIBRA_DB", "sqlite:///./calibra.db")


def criar_engine(url: str = URL):
    args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    eng = create_engine(url, connect_args=args)
    Base.metadata.create_all(eng)
    return eng


engine = criar_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
