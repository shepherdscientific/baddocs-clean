"""PHP code processor."""

from baddocs.processors.base import BaseProcessor

class PHPProcessor(BaseProcessor):
    """Processor for PHP code."""
    
    def __init__(self):
        super().__init__()
        self.language = 'php'
    
    def parse(self, code: str):
        """Parse PHP code."""
        return {'ast': None}
    
    def extract_symbols(self, code: str):
        """Extract PHP symbols."""
        return []
