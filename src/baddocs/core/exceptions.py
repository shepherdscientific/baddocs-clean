"""BadDocs exceptions."""

class BadDocsException(Exception):
    """Base exception for BadDocs."""
    pass

class ConfigError(BadDocsException):
    """Configuration error."""
    pass

class AnalysisError(BadDocsException):
    """Analysis error."""
    pass

class StorageError(BadDocsException):
    """Storage error."""
    pass
