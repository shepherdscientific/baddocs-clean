"""
FastAPI main application for BadDocs Repository Documentation System.

Provides REST API endpoints for GitHub App integration, repository analysis,
incremental documentation generation, and system monitoring.
Designed for automated documentation of entire GitHub repositories.
"""

import os
import logging
import asyncio
import secrets
from typing import Dict, List, Any, Optional
from contextlib import asynccontextmanager
from datetime import datetime

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Request, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pathlib import Path

# BadDocs imports
from ..config.providers_simple import (
    SimpleProvidersConfigManager as ProvidersConfigManager,
    SimpleProviderRegistry as ProviderRegistry,
    providers_config
)

# Full LLM types for model router and internal use
from ..mcp_servers.llm.providers.base import LLMRequest, LLMResponse

# Storage system integration
try:
    from ..storage.connection import StorageManager
    from ..storage.file_ops import FileOperations
    from ..storage.document_ops import DocumentOperations
    from ..storage.search import SearchEngine
    HAS_STORAGE_SUPPORT = True
    logging.info("Storage system enabled with SQLite FTS5 support")
except ImportError as e:
    logging.warning(f"Storage system not available: {e}")
    HAS_STORAGE_SUPPORT = False

# MCP Integration for orchestrated processing
try:
    from .mcp_integration import MCPWebIntegration, MCPClientError
    HAS_MCP_SUPPORT = True
    logging.info("MCP orchestration support enabled")
except ImportError as e:
    logging.warning(f"MCP integration not available: {e}")
    HAS_MCP_SUPPORT = False
