"""File discovery for source code analysis."""

import os
from pathlib import Path
from typing import List, Set

class FileDiscovery:
    """Discovers files in a repository for analysis."""
    
    DEFAULT_IGNORE_DIRS = {
        '.git', '.github', '__pycache__', 'node_modules',
        '.venv', 'venv', '.tox', '.pytest_cache', 'dist', 'build'
    }
    
    def __init__(self, root_path: str, ignore_dirs: Set[str] = None):
        """Initialize file discovery.
        
        Args:
            root_path: Root directory to start discovery
            ignore_dirs: Set of directories to ignore
        """
        self.root_path = Path(root_path)
        self.ignore_dirs = ignore_dirs or self.DEFAULT_IGNORE_DIRS
    
    def discover(self, extensions: List[str] = None) -> List[Path]:
        """Discover files matching given extensions.
        
        Args:
            extensions: List of file extensions to match (e.g., ['.py', '.java'])
        
        Returns:
            List of Path objects for matching files
        """
        files = []
        for item in self.root_path.rglob('*'):
            if item.is_file():
                if self._should_include(item, extensions):
                    files.append(item)
        return sorted(files)
    
    def _should_include(self, path: Path, extensions: List[str]) -> bool:
        """Check if file should be included.
        
        Args:
            path: File path to check
            extensions: List of allowed extensions
        
        Returns:
            True if file should be included
        """
        # Check if any parent directory should be ignored
        for part in path.parts:
            if part in self.ignore_dirs:
                return False
        
        # Check extension if specified
        if extensions and path.suffix not in extensions:
            return False
        
        return True
