"""Detects changes for incremental analysis."""

class ChangeDetector:
    """Detects code changes."""
    
    def detect(self, old_code: str, new_code: str) -> list:
        """Detect changes between code versions.
        
        Args:
            old_code: Previous version
            new_code: Current version
        
        Returns:
            List of changes
        """
        return []
