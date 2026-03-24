"""COBOL code processor."""

from baddocs.processors.base import BaseProcessor

class CobolProcessor(BaseProcessor):
    """Processor for COBOL code."""
    
    def __init__(self):
        super().__init__()
        self.language = 'cobol'
    
    def parse(self, code: str):
        """Parse COBOL code."""
        return {'ast': None}
    
    def extract_symbols(self, code: str):
        """Extract COBOL symbols."""
        return []
