"""Test configuration and fixtures."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from baddocs.storage.models import Base

@pytest.fixture(scope='session')
def db_engine():
    """Create test database engine."""
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(bind=engine)
    return engine

@pytest.fixture(scope='function')
def db_session(db_engine):
    """Create test database session."""
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    yield session
    session.close()
