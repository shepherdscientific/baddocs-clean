"""Impact analysis engine."""

class ImpactEngine:
    """Engine for impact analysis."""
    
    def __init__(self, graph):
        self.graph = graph
    
    def get_affected_modules(self, changed_file: str) -> list:
        """Get modules affected by change.
        
        Args:
            changed_file: Changed file path
        
        Returns:
            List of affected modules
        """
        return []
