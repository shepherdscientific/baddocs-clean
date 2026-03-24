"""Python code processor."""

from baddocs.processors.base import BaseProcessor

class PythonProcessor(BaseProcessor):
    """Processor for Python code."""
    
    def __init__(self):
        super().__init__()
        self.language = 'python'
    
    def parse(self, code: str):
        """Parse Python code."""
        return {'ast': None}
    
    def extract_symbols(self, code: str):
        """Extract Python symbols."""
        return []
