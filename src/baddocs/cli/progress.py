"""Progress tracking for CLI."""

class ProgressTracker:
    """Tracks progress of operations."""
    
    def __init__(self, total):
        self.total = total
        self.current = 0
    
    def update(self, amount=1):
        """Update progress."""
        self.current += amount
    
    def percentage(self):
        """Get percentage complete."""
        return (self.current / self.total) * 100 if self.total > 0 else 0
