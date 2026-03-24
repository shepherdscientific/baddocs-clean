"""Business logic pattern detection."""

class BusinessLogicPatterns:
    """Detects business logic patterns."""
    
    PATTERNS = [
        'transaction',
        'validation',
        'calculation',
        'workflow'
    ]
    
    @classmethod
    def detect(cls, code: str) -> list:
        """Detect patterns in code.
        
        Args:
            code: Source code
        
        Returns:
            List of detected patterns
        """
        found = []
        for pattern in cls.PATTERNS:
            if pattern in code.lower():
                found.append(pattern)
        return found
