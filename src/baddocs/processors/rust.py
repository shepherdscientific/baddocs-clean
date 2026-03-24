"""Rust code processor."""

from baddocs.processors.base import BaseProcessor

class RustProcessor(BaseProcessor):
    """Processor for Rust code."""
    
    def __init__(self):
        super().__init__()
        self.language = 'rust'
    
    def parse(self, code: str):
        """Parse Rust code."""
        return {'ast': None}
    
    def extract_symbols(self, code: str):
        """Extract Rust symbols."""
        return []
