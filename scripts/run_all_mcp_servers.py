#!/usr/bin/env python3
"""Run all MCP servers."""

from baddocs.mcp_servers.orchestrator import ServerOrchestrator
from baddocs.mcp_servers.registry import ServerRegistry

def main():
    registry = ServerRegistry()
    orchestrator = ServerOrchestrator(registry)
    orchestrator.start_all()

if __name__ == '__main__':
    main()
