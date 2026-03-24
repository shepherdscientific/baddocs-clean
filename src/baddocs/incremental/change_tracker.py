"""Tracks changes over time."""

class ChangeTracker:
    """Tracks code changes over time."""
    
    def __init__(self):
        self.history = []
    
    def record_change(self, file_path: str, change_type: str):
        """Record a change.
        
        Args:
            file_path: Path to changed file
            change_type: Type of change
        """
        self.history.append({
            'file': file_path,
            'type': change_type
        })
