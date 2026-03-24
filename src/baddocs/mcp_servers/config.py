"""MCP server configuration."""

class MCPServerConfig:
    """Configuration for MCP servers."""
    
    def __init__(self, name: str, command: str, port: int = None):
        self.name = name
        self.command = command
        self.port = port
