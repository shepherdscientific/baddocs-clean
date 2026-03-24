"""MCP server orchestrator."""

class ServerOrchestrator:
    """Orchestrates MCP servers."""
    
    def __init__(self, registry):
        self.registry = registry
    
    def start_all(self):
        """Start all registered servers."""
        for server in self.registry.servers.values():
            server.start()
    
    def stop_all(self):
        """Stop all running servers."""
        for server in self.registry.servers.values():
            server.stop()
