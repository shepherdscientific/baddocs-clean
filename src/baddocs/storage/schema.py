"""Database schema utilities."""

from baddocs.storage.models import Base
from sqlalchemy import create_engine

def create_tables(engine):
    """Create all tables.
    
    Args:
        engine: SQLAlchemy engine
    """
    Base.metadata.create_all(bind=engine)

def drop_tables(engine):
    """Drop all tables.
    
    Args:
        engine: SQLAlchemy engine
    """
    Base.metadata.drop_all(bind=engine)
