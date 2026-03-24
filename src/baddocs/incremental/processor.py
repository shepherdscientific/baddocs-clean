"""Incremental analysis processor."""

from baddocs.incremental.base import IncrementalBase

class IncrementalProcessor(IncrementalBase):
    """Processes incremental analysis."""
    
    def process(self, changes: list) -> dict:
        """Process changes.
        
        Args:
            changes: List of code changes
        
        Returns:
            Analysis results
        """
        return {
            'analyzed_files': len(changes),
            'issues_found': []
        }
