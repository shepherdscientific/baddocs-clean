"""Java code processor."""

from baddocs.processors.base import BaseProcessor

class JavaProcessor(BaseProcessor):
    """Processor for Java code."""
    
    def __init__(self):
        super().__init__()
        self.language = 'java'
    
    def parse(self, code: str):
        """Parse Java code."""
        return {'ast': None}
    
    def extract_symbols(self, code: str):
        """Extract Java symbols."""
        return []
