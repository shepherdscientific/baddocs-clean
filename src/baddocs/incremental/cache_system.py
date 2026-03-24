"""Caching system for incremental analysis."""

class CacheSystem:
    """Manages analysis cache."""
    
    def __init__(self):
        self.cache = {}
    
    def get(self, key: str):
        """Get cached value."""
        return self.cache.get(key)
    
    def set(self, key: str, value):
        """Set cached value."""
        self.cache[key] = value
    
    def invalidate(self, key: str):
        """Invalidate cache entry."""
        if key in self.cache:
            del self.cache[key]
