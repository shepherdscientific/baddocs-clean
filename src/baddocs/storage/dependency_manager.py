"""Dependency management."""

class DependencyManager:
    """Manages dependencies."""
    
    def __init__(self, session):
        self.session = session
    
    def add_dependency(self, source_id: int, target_id: int):
        """Add dependency.
        
        Args:
            source_id: Source document ID
            target_id: Target document ID
        """
        pass
    
    def get_dependencies(self, doc_id: int) -> list:
        """Get dependencies for document.
        
        Args:
            doc_id: Document ID
        
        Returns:
            List of dependencies
        """
        return []
