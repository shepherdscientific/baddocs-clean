"""Documentation generators."""

from typing import Dict, Any

class GeneratorRegistry:
    """Registry for documentation generators."""
    
    def __init__(self):
        self.generators: Dict[str, Any] = {}
    
    def register(self, name: str, generator):
        """Register a generator."""
        self.generators[name] = generator
    
    def get(self, name: str):
        """Get a generator by name."""
        return self.generators.get(name)

_registry = GeneratorRegistry()

__all__ = ['GeneratorRegistry']
