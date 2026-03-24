"""File operations."""

class FileOperations:
    """Operations on files."""
    
    @staticmethod
    def read_file(path: str) -> str:
        """Read file.
        
        Args:
            path: File path
        
        Returns:
            File contents
        """
        with open(path, 'r') as f:
            return f.read()
    
    @staticmethod
    def write_file(path: str, content: str):
        """Write file.
        
        Args:
            path: File path
            content: File contents
        """
        with open(path, 'w') as f:
            f.write(content)
