"""Vendor-specific patterns."""

class VendorPatterns:
    """Detects vendor-specific patterns."""
    
    @staticmethod
    def detect_spring_patterns(code: str) -> list:
        """Detect Spring Framework patterns."""
        patterns = []
        if '@SpringBootApplication' in code:
            patterns.append('spring-boot')
        return patterns
    
    @staticmethod
    def detect_django_patterns(code: str) -> list:
        """Detect Django patterns."""
        patterns = []
        if 'from django' in code:
            patterns.append('django')
        return patterns
