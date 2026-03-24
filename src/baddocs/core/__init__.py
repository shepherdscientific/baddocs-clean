"""Core functionality for BadDocs."""

from baddocs.core.file_discovery import FileDiscovery
from baddocs.core.exceptions import BadDocsException

__all__ = [
    'FileDiscovery',
    'BadDocsException',
]
