"""Search functionality."""

class SearchEngine:
    """Full-text search engine."""
    
    def __init__(self, session):
        self.session = session
    
    def search(self, query: str, limit: int = 10) -> list:
        """Search documents.
        
        Args:
            query: Search query
            limit: Result limit
        
        Returns:
            Search results
        """
        return []
