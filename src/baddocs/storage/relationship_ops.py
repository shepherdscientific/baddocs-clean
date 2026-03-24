"""Relationship operations."""

class RelationshipOperations:
    """Operations on relationships."""
    
    def __init__(self, session):
        self.session = session
    
    def create_relationship(self, source_id: int, target_id: int, rel_type: str):
        """Create relationship."""
        pass
    
    def get_relationships(self, entity_id: int) -> list:
        """Get relationships."""
        return []
