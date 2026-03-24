"""Document operations."""

class DocumentOperations:
    """Operations on documents."""
    
    def __init__(self, session):
        self.session = session
    
    def create_document(self, repo_id: int, name: str, content: str):
        """Create document."""
        pass
    
    def update_document(self, doc_id: int, content: str):
        """Update document."""
        pass
    
    def delete_document(self, doc_id: int):
        """Delete document."""
        pass
