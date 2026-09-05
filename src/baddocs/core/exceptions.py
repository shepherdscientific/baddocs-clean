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

class ProcessingError(BadDocsException):
    """Raised when file processing fails."""
    pass
