"""Database connection management."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from typing import Optional

SessionLocal: Optional[sessionmaker] = None

def init_db(database_url: str):
    """Initialize database connection.
    
    Args:
        database_url: Database URL
    """
    global SessionLocal
    engine = create_engine(database_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_session():
    """Get database session.
    
    Returns:
        Database session
    """
    if SessionLocal is None:
        raise RuntimeError('Database not initialized')
    return SessionLocal()
