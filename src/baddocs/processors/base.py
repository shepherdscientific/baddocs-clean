"""Base processor for all languages."""

from abc import ABC, abstractmethod
from typing import List, Dict, Any

class BaseProcessor(ABC):
    """Base class for language processors."""
    
    def __init__(self):
        self.language = None
    
    @abstractmethod
    def parse(self, code: str) -> Dict[str, Any]:
        """Parse source code.
        
        Args:
            code: Source code
        
        Returns:
            Parsed code structure
        """
        pass
    
    @abstractmethod
    def extract_symbols(self, code: str) -> List[Dict[str, Any]]:
        """Extract symbols from code.
        
        Args:
            code: Source code
        
        Returns:
            List of symbols
        """
        pass
