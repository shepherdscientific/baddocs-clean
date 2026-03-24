"""Performance monitoring."""

class PerformanceMonitor:
    """Monitors storage performance."""
    
    def __init__(self, engine):
        self.engine = engine
    
    def get_metrics(self) -> dict:
        """Get performance metrics.
        
        Returns:
            Performance metrics
        """
        return {
            'query_count': 0,
            'avg_query_time': 0,
            'slow_queries': []
        }
