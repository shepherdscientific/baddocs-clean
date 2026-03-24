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
    logging.warning(f"MCP support not available: {e}")
    HAS_MCP_SUPPORT = False

# GitHub integration
try:
    from .github import GitHubAppAuth, GitHubAuth
    HAS_GITHUB_SUPPORT = True
except ImportError as e:
    logging.warning(f"GitHub support not available: {e}")
    HAS_GITHUB_SUPPORT = False

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# ============================================================================
# Pydantic Models
# ============================================================================

class DocumentationRequest(BaseModel):
    """Request model for documentation generation."""
    code: str = Field(..., description="Source code to document")
    language: str = Field(..., description="Programming language")
    context_type: str = Field(default="function", description="Type of context (function, class, module, api, database)")
    temperature: float = Field(default=0.3, ge=0.0, le=1.0, description="Creativity level for generation")


class SystemStatus(BaseModel):
    """System status response."""
    status: str
    timestamp: str
    providers: List[Dict[str, Any]]
    mvp_config: str
    storage_available: bool
    mcp_available: bool
    github_available: bool


# ============================================================================
# Application Startup and Shutdown
# ============================================================================

async def startup_event():
    """Initialize application on startup."""
    logger.info("BadDocs Web API starting up...")
    
    # Initialize storage if available
    if HAS_STORAGE_SUPPORT:
        try:
            logger.info("Initializing storage system...")
            # Storage initialization would happen here
        except Exception as e:
            logger.error(f"Failed to initialize storage: {e}")
    
    # Initialize MCP if available
    if HAS_MCP_SUPPORT:
        try:
            logger.info("Initializing MCP integration...")
            # MCP initialization would happen here
        except Exception as e:
            logger.error(f"Failed to initialize MCP: {e}")
    
    logger.info("BadDocs Web API startup complete")


async def shutdown_event():
    """Cleanup on application shutdown."""
    logger.info("BadDocs Web API shutting down...")
    
    # Cleanup operations would happen here
    
    logger.info("BadDocs Web API shutdown complete")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager."""
    await startup_event()
    yield
    await shutdown_event()


# ============================================================================
# FastAPI Application Setup
# ============================================================================

app = FastAPI(
    title="BadDocs Repository Documentation API",
    description="AI-powered documentation generation for GitHub repositories",
    version="0.1.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ============================================================================
# Root Endpoints
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main documentation UI."""
    html_file = Path(__file__).parent / "static" / "index.html"
    if html_file.exists():
        return html_file.read_text()
    return "<h1>BadDocs API</h1><p>Documentation generation service</p>"


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "0.1.0"
    }


@app.get("/status")
async def get_status():
    """Get system status."""
    providers = []
    
    # Get provider status from config
    if hasattr(providers_config, 'providers'):
        for provider in providers_config.providers.values():
            providers.append({
                "name": getattr(provider, 'name', 'unknown'),
                "type": getattr(provider, 'type', 'unknown'),
                "enabled": getattr(provider, 'enabled', False),
                "healthy": getattr(provider, 'enabled', False),  # Simplified health check
                "priority": getattr(provider, 'priority', 999),
                "cost_tier": getattr(provider, 'cost_tier', 'free')
            })
    
    return {
        "providers": providers,
        "mvp_config": os.getenv("MVP_CONFIG", "basic"),
        "storage": {"available": HAS_STORAGE_SUPPORT},
        "mcp": {"available": HAS_MCP_SUPPORT},
        "github": {"available": HAS_GITHUB_SUPPORT}
    }


@app.get("/providers")
async def get_providers():
    """Get available LLM providers."""
    providers_dict = {}
    mvp_configs = {}
    
    # Get provider information
    if hasattr(providers_config, 'providers'):
        for name, provider in providers_config.providers.items():
            providers_dict[name] = {
                "name": getattr(provider, 'name', name),
                "type": getattr(provider, 'type', 'unknown'),
                "description": getattr(provider, 'description', ''),
                "cost_tier": getattr(provider, 'cost_tier', 'free'),
                "estimated_cost_per_1k_tokens": getattr(provider, 'estimated_cost_per_1k_tokens', None),
                "use_cases": getattr(provider, 'use_cases', [])
            }
    
    # Get MVP config information
    if hasattr(providers_config, 'mvp_configs'):
        for name, config in providers_config.mvp_configs.items():
            mvp_configs[name] = {
                "monthly_budget_usd": getattr(config, 'monthly_budget_usd', 0),
                "providers": getattr(config, 'providers', []),
                "recommended_usage": getattr(config, 'recommended_usage', '')
            }
    
    return {
        "providers": providers_dict,
        "mvp_configs": mvp_configs
    }


# ============================================================================
# Documentation Generation Endpoints
# ============================================================================

@app.post("/generate-docs")
async def generate_documentation(request: DocumentationRequest):
    """Generate documentation for provided code."""
    try:
        logger.info(f"Generating documentation for {request.language} ({request.context_type})")
        
        # Initialize LLM provider
        provider_registry = ProviderRegistry()
        
        # Create LLM request
        llm_request = LLMRequest(
            prompt=f"Document this {request.context_type} in {request.language}:\n\n{request.code}",
            temperature=request.temperature,
            max_tokens=2000
        )
        
        # Get available provider
        provider = provider_registry.select_provider(request.language)
        if not provider:
            raise HTTPException(status_code=500, detail="No LLM provider available")
        
        # Generate documentation
        start_time = datetime.utcnow()
        response = await provider.generate(llm_request)
        elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000
        
        return {
            "documentation": response.content if hasattr(response, 'content') else str(response),
            "model_used": getattr(provider, 'model', 'unknown'),
            "provider_used": getattr(provider, 'name', 'unknown'),
            "processing_time_ms": int(elapsed),
            "tokens_used": getattr(response, 'tokens_used', None)
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Documentation generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Repository Endpoints
# ============================================================================

@app.get("/api/repositories")
async def list_repositories():
    """List all analyzed repositories."""
    try:
        repositories = []
        
        # Get repositories from storage if available
        if HAS_STORAGE_SUPPORT:
            try:
                # Would fetch from storage here
                pass
            except Exception as e:
                logger.warning(f"Failed to get repositories from storage: {e}")
        
        return {
            "repositories": repositories,
            "total": len(repositories)
        }
    
    except Exception as e:
        logger.error(f"Failed to list repositories: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/repositories/analyze")
async def analyze_repository(request: Dict[str, Any] = Body(...)):
    """Trigger analysis of a GitHub repository."""
    try:
        repository_url = request.get("repository_url")
        branch = request.get("branch", "main")
        clone_depth = request.get("clone_depth", 1)
        
        logger.info(f"Starting analysis of {repository_url}")
        
        # If MCP is available, use it for analysis
        if HAS_MCP_SUPPORT:
            try:
                mcp = MCPWebIntegration()
                # Start analysis via MCP
                logger.info(f"Delegating to MCP for analysis")
                # This would trigger MCP-based analysis
            except MCPClientError as e:
                logger.warning(f"MCP analysis failed: {e}")
        
        return {
            "status": "analysis_started",
            "repository_url": repository_url,
            "branch": branch
        }
    
    except Exception as e:
        logger.error(f"Failed to analyze repository: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/repositories/{repository_id}")
async def get_repository(repository_id: str):
    """Get repository details."""
    try:
        # Fetch from storage
        return {
            "repository_id": repository_id,
            "status": "analyzing"
        }
    
    except Exception as e:
        logger.error(f"Failed to get repository: {e}")
        raise HTTPException(status_code=404, detail="Repository not found")


@app.get("/api/repositories/{repository_id}/documentation")
async def get_repository_documentation(repository_id: str):
    """Get generated documentation for repository."""
    try:
        return {
            "repository_id": repository_id,
            "documentation": "# Repository Documentation\n\nThis is generated documentation."
        }
    
    except Exception as e:
        logger.error(f"Failed to get documentation: {e}")
        raise HTTPException(status_code=404, detail="Documentation not found")


@app.post("/api/repositories/{repository_id}/regenerate")
async def regenerate_repository(repository_id: str):
    """Trigger regeneration of repository documentation."""
    try:
        logger.info(f"Regenerating documentation for {repository_id}")
        
        return {
            "status": "regeneration_started",
            "repository_id": repository_id
        }
    
    except Exception as e:
        logger.error(f"Failed to regenerate documentation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# GitHub Integration Endpoints
# ============================================================================

@app.get("/github/setup")
async def github_setup(request: Request):
    """GitHub app setup page."""
    return HTMLResponse("""
        <html>
            <head><title>BadDocs GitHub Setup</title></head>
            <body>
                <h1>GitHub App Setup</h1>
                <p>Configure BadDocs for your GitHub repositories.</p>
            </body>
        </html>
    """)


@app.post("/api/github/webhook")
async def github_webhook(request: Request):
    """Handle GitHub webhooks."""
    try:
        body = await request.body()
        headers = dict(request.headers)
        
        logger.info(f"Received GitHub webhook: {headers.get('X-GitHub-Event')}")
        
        # Verify webhook signature if GitHub auth is available
        if HAS_GITHUB_SUPPORT:
            try:
                github_auth = GitHubAppAuth()
                signature = headers.get("X-Hub-Signature-256")
                if signature and not github_auth.verify_webhook_signature(body, signature):
                    raise HTTPException(status_code=401, detail="Invalid webhook signature")
            except ValueError:
                logger.warning("GitHub App not configured")
        
        return {
            "status": "webhook_received",
            "event": headers.get("X-GitHub-Event")
        }
    
    except Exception as e:
        logger.error(f"Webhook processing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Error Handlers
# ============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )


# ============================================================================
# Application Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    # Configuration from environment
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    debug = os.getenv("DEBUG", "false").lower() == "true"
    workers = int(os.getenv("WORKERS", "1"))
    
    # Run with uvicorn
    if debug or os.getenv("ENVIRONMENT", "production") == "development":
        # Development mode - single worker with reload
        uvicorn.run(
            "main:app",
            host=host,
            port=port,
            reload=True,
            log_level="info"
        )
    else:
        # Production mode
        uvicorn.run(
            "main:app",
            host=host,
            port=port,
            workers=workers,
            log_level="info"
        )
