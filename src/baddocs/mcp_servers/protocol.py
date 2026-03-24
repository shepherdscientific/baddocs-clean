"""MCP protocol implementation."""

class MCPMessage:
    """MCP protocol message."""
    
    def __init__(self, msg_type: str, data: dict):
        self.msg_type = msg_type
        self.data = data
    
    def to_dict(self):
        """Convert to dictionary."""
        return {
            'type': self.msg_type,
            'data': self.data
        }
