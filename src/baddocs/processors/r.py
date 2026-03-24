"""R code processor."""

from baddocs.processors.base import BaseProcessor

class RProcessor(BaseProcessor):
    """Processor for R code."""
    
    def __init__(self):
        super().__init__()
        self.language = 'r'
    
    def parse(self, code: str):
        """Parse R code."""
        return {'ast': None}
    
    def extract_symbols(self, code: str):
        """Extract R symbols."""
        return []
