"""MCP server registry."""

class ServerRegistry:
    """Registry for MCP servers."""
    
    def __init__(self):
        self.servers = {}
    
    def register(self, name: str, server):
        """Register server.
        
        Args:
            name: Server name
            server: Server instance
        """
        self.servers[name] = server
    
    def get(self, name: str):
        """Get server by name.
        
        Args:
            name: Server name
        
        Returns:
            Server instance
        """
        return self.servers.get(name)
