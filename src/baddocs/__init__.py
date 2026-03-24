"""BadDocs - AI-powered documentation for legacy codebases."""

__version__ = '1.0.0'
__author__ = 'Shepherd Scientific'

from baddocs.core.file_discovery import FileDiscovery
from baddocs.storage.connection import get_session

__all__ = [
    'FileDiscovery',
    'get_session',
]
