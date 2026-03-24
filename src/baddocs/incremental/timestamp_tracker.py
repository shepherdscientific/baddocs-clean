"""Tracks timestamps for cache invalidation."""

from datetime import datetime

class TimestampTracker:
    """Tracks modification timestamps."""
    
    def __init__(self):
        self.timestamps = {}
    
    def track(self, file_path: str):
        """Track file modification time.
        
        Args:
            file_path: Path to file
        """
        self.timestamps[file_path] = datetime.utcnow()
    
    def get_time(self, file_path: str) -> datetime:
        """Get last modification time.
        
        Args:
            file_path: Path to file
        
        Returns:
            Modification datetime
        """
        return self.timestamps.get(file_path)
