"""C# code processor."""

from baddocs.processors.base import BaseProcessor

class CSharpProcessor(BaseProcessor):
    """Processor for C# code."""
    
    def __init__(self):
        super().__init__()
        self.language = 'csharp'
    
    def parse(self, code: str):
        """Parse C# code."""
        return {'ast': None}
    
    def extract_symbols(self, code: str):
        """Extract C# symbols."""
        return []
