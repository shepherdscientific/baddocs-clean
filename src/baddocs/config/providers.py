"""Provider configuration."""

class ProviderConfig:
    """Provider configuration."""
    
    def __init__(self, provider_name: str, config: dict):
        self.name = provider_name
        self.config = config
    
    def is_enabled(self) -> bool:
        """Check if provider is enabled."""
        return self.config.get('enabled', False)
