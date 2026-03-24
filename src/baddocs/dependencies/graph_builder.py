"""Build dependency graphs."""

class DependencyGraphBuilder:
    """Builds dependency graphs."""
    
    def __init__(self):
        self.nodes = {}
        self.edges = []
    
    def add_dependency(self, source: str, target: str):
        """Add dependency.
        
        Args:
            source: Source module
            target: Target module
        """
        self.edges.append((source, target))
    
    def build(self) -> dict:
        """Build graph.
        
        Returns:
            Dependency graph
        """
        return {
            'nodes': self.nodes,
            'edges': self.edges
        }
