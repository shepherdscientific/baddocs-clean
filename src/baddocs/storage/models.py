"""Database models."""

from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Table
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()

class Repository(Base):
    """Repository model."""
    __tablename__ = 'repositories'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, index=True)
    url = Column(String(512))
    language = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    documents = relationship('Document', back_populates='repository')

class Document(Base):
    """Document model."""
    __tablename__ = 'documents'
    
    id = Column(Integer, primary_key=True)
    repository_id = Column(Integer, ForeignKey('repositories.id'))
    name = Column(String(512))
    path = Column(String(512))
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    repository = relationship('Repository', back_populates='documents')
