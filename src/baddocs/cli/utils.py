"""CLI utility functions."""

def validate_path(path):
    """Validate a file path."""
    import os
    return os.path.exists(path)
