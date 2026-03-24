"""PowerBuilder code processor."""

from baddocs.processors.base import BaseProcessor

class PowerBuilderProcessor(BaseProcessor):
    """Processor for PowerBuilder code."""
    
    def __init__(self):
        super().__init__()
        self.language = 'powerbuilder'
    
    def parse(self, code: str):
        """Parse PowerBuilder code."""
        return {'ast': None}
    
    def extract_symbols(self, code: str):
        """Extract PowerBuilder symbols."""
        return []
