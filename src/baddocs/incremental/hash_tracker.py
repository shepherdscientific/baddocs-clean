"""Tracks file hashes for change detection."""

import hashlib

class HashTracker:
    """Tracks file hashes."""
    
    def __init__(self):
        self.hashes = {}
    
    def get_hash(self, content: str) -> str:
        """Get hash of content.
        
        Args:
            content: File content
        
        Returns:
            SHA256 hash
        """
        return hashlib.sha256(content.encode()).hexdigest()
    
    def track(self, file_path: str, content: str):
        """Track file hash.
        
        Args:
            file_path: Path to file
            content: File content
        """
        self.hashes[file_path] = self.get_hash(content)
    
    def has_changed(self, file_path: str, content: str) -> bool:
        """Check if file has changed.
        
        Args:
            file_path: Path to file
            content: Current content
        
        Returns:
            True if changed
        """
        return self.hashes.get(file_path) != self.get_hash(content)
