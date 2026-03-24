"""JavaScript code processor."""

from baddocs.processors.base import BaseProcessor

class JavaScriptProcessor(BaseProcessor):
    """Processor for JavaScript code."""
    
    def __init__(self):
        super().__init__()
        self.language = 'javascript'
    
    def parse(self, code: str):
        """Parse JavaScript code."""
        return {'ast': None}
    
    def extract_symbols(self, code: str):
        """Extract JavaScript symbols."""
        return []
