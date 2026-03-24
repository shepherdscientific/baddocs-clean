"""Repository configuration."""

class RepositoryConfig:
    """Configuration for repositories."""
    
    def __init__(self, session):
        self.session = session
    
    def get_language_config(self, repo_id: int) -> dict:
        """Get language configuration."""
        return {}
    
    def set_language_config(self, repo_id: int, config: dict):
        """Set language configuration."""
        pass
