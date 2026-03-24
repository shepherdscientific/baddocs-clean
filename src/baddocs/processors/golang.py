"""Go code processor."""

from baddocs.processors.base import BaseProcessor

class GoProcessor(BaseProcessor):
    """Processor for Go code."""
    
    def __init__(self):
        super().__init__()
        self.language = 'go'
    
    def parse(self, code: str):
        """Parse Go code."""
        return {'ast': None}
    
    def extract_symbols(self, code: str):
        """Extract Go symbols."""
        return []
