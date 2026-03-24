"""Base MCP server."""

from abc import ABC, abstractmethod

class BaseMCPServer(ABC):
    """Base class for MCP servers."""
    
    def __init__(self, name: str, port: int):
        self.name = name
        self.port = port
        self.running = False
    
    @abstractmethod
    def start(self):
        """Start the server."""
        pass
    
    @abstractmethod
    def stop(self):
        """Stop the server."""
        pass
    
    @abstractmethod
    def handle_request(self, request):
        """Handle incoming request."""
        pass
