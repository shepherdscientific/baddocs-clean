"""Base incremental analysis."""

class IncrementalBase:
    """Base class for incremental analysis."""
    
    def __init__(self):
        self.last_state = None
    
    def should_analyze(self, current_state):
        """Check if analysis should run.
        
        Args:
            current_state: Current code state
        
        Returns:
            True if analysis needed
        """
        return current_state != self.last_state
