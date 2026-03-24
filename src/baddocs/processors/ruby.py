"""Ruby code processor."""

from baddocs.processors.base import BaseProcessor

class RubyProcessor(BaseProcessor):
    """Processor for Ruby code."""
    
    def __init__(self):
        super().__init__()
        self.language = 'ruby'
    
    def parse(self, code: str):
        """Parse Ruby code."""
        return {'ast': None}
    
    def extract_symbols(self, code: str):
        """Extract Ruby symbols."""
        return []
