"""VB6 code processor."""

from baddocs.processors.base import BaseProcessor

class VB6Processor(BaseProcessor):
    """Processor for Visual Basic 6 code."""
    
    def __init__(self):
        super().__init__()
        self.language = 'vb6'
    
    def parse(self, code: str):
        """Parse VB6 code."""
        return {'ast': None}
    
    def extract_symbols(self, code: str):
        """Extract VB6 symbols."""
        return []
