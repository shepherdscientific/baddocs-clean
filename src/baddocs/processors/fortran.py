"""Fortran code processor."""

from baddocs.processors.base import BaseProcessor

class FortranProcessor(BaseProcessor):
    """Processor for Fortran code."""
    
    def __init__(self):
        super().__init__()
        self.language = 'fortran'
    
    def parse(self, code: str):
        """Parse Fortran code."""
        return {'ast': None}
    
    def extract_symbols(self, code: str):
        """Extract Fortran symbols."""
        return []
