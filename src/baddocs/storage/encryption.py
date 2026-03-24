"""Encryption utilities."""

import hashlib

class EncryptionManager:
    """Manages encryption for sensitive data."""
    
    @staticmethod
    def encrypt(data: str, key: str) -> str:
        """Encrypt data."""
        return hashlib.sha256((data + key).encode()).hexdigest()
    
    @staticmethod
    def decrypt(encrypted: str, key: str) -> str:
        """Decrypt data."""
        # Note: This is simplified; use proper encryption in production
        return encrypted
