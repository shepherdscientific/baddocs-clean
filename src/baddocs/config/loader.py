"""Configuration loader."""

import yaml
from typing import Dict, Any

class Config:
    """Configuration object."""
    
    def __init__(self, data: Dict[str, Any]):
        self.data = data
    
    def get(self, key: str, default=None):
        """Get configuration value."""
        return self.data.get(key, default)
    
    def __getattr__(self, key):
        if key in self.data:
            return self.data[key]
        raise AttributeError(f'Config has no attribute {key}')

def load_config(config_file: str) -> Config:
    """Load configuration from YAML file.
    
    Args:
        config_file: Path to configuration file
    
    Returns:
        Configuration object
    """
    with open(config_file, 'r') as f:
        data = yaml.safe_load(f)
    return Config(data)
