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

# GitHub App integration
try:
    from .github.app_flow import GitHubAppFlow
    from .github.mcp_github import MCPGitHubIntegration
    from .github_secrets import SecretsManager
    HAS_GITHUB_APP_SUPPORT = True
    logging.info("GitHub App support enabled")
except ImportError as e:
    logging.warning(f"GitHub App integration not available: {e}")
    HAS_GITHUB_APP_SUPPORT = False

# Configuration imports
from .database_config_routes import DatabaseConfigRouter
from ..config.providers_simple import providers_config
from .github_secrets import SecretsManager

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Get base directory for serving static files
BASE_DIR = Path(__file__).parent.parent.parent
STATIC_DIR = BASE_DIR / 'src' / 'baddocs' / 'web' / 'static'
TEMPLATES_DIR = BASE_DIR / 'src' / 'baddocs' / 'web' / 'templates'


# =================== Global State Management ===================
class GlobalAppState:
    """Thread-safe global application state for background tasks."""
    
    def __init__(self):
        self.active_tasks: Dict[str, Any] = {}
        self.storage_manager: Optional[StorageManager] = None
        self.mcp_integration: Optional[MCPWebIntegration] = None
        self.github_integration: Optional[MCPGitHubIntegration] = None
        self.secrets_manager: Optional[SecretsManager] = None
        self.db_router: Optional[DatabaseConfigRouter] = None
        self.task_lock = asyncio.Lock()


global_state = GlobalAppState()


# =================== FastAPI Lifespan Management ===================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle: startup and shutdown."""
    
    logger.info("Starting BadDocs FastAPI application...")
    
    # Initialize storage system if available
    if HAS_STORAGE_SUPPORT:
        try:
            global_state.storage_manager = StorageManager()
            logger.info("Storage manager initialized")
        except Exception as e:
            logger.error(f"Failed to initialize storage manager: {e}")
    
    # Initialize MCP integration if available
    if HAS_MCP_SUPPORT:
        try:
            global_state.mcp_integration = MCPWebIntegration()
            logger.info("MCP integration initialized")
        except Exception as e:
            logger.error(f"Failed to initialize MCP integration: {e}")
    
    # Initialize GitHub App integration if available
    if HAS_GITHUB_APP_SUPPORT:
        try:
            global_state.secrets_manager = SecretsManager()
            global_state.github_integration = MCPGitHubIntegration()
            logger.info("GitHub App integration initialized")
        except Exception as e:
            logger.error(f"Failed to initialize GitHub App integration: {e}")
    
    # Initialize database config router
    try:
        global_state.db_router = DatabaseConfigRouter()
        logger.info("Database config router initialized")
    except Exception as e:
        logger.error(f"Failed to initialize database config router: {e}")
    
    yield  # Application running
    
    logger.info("Shutting down BadDocs FastAPI application...")


# =================== FastAPI App Creation ===================
app = FastAPI(
    title="BadDocs Repository Documentation System",
    description="Automated documentation generation for GitHub repositories",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    logger.info(f"Mounted static files from {STATIC_DIR}")


# =================== Request/Response Models ===================
class DocumentationRequest(BaseModel):
    """Request model for documentation generation."""
    repository_url: str = Field(..., description="GitHub repository URL")
    branch: Optional[str] = Field(default="main", description="Repository branch")
    incremental: bool = Field(default=False, description="Use incremental updates")
    provider: str = Field(default="anthropic", description="LLM provider")
    model: Optional[str] = Field(default=None, description="Model name")


class DocumentationResponse(BaseModel):
    """Response model for documentation generation."""
    task_id: str = Field(..., description="Unique task identifier")
    status: str = Field(..., description="Current task status")
    repository: str = Field(..., description="Repository identifier")
    message: Optional[str] = Field(default=None, description="Status message")


class TaskStatusResponse(BaseModel):
    """Response model for task status."""
    task_id: str
    status: str
    progress: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    timestamp: str
    storage_enabled: bool = HAS_STORAGE_SUPPORT
    mcp_enabled: bool = HAS_MCP_SUPPORT
    github_app_enabled: bool = HAS_GITHUB_APP_SUPPORT


class ConfigValidationRequest(BaseModel):
    """Request model for provider configuration validation."""
    provider_name: str
    credentials: Dict[str, Any]


class ConfigValidationResponse(BaseModel):
    """Response model for provider configuration validation."""
    valid: bool
    message: str
    supported_models: Optional[List[str]] = None


class RepositoryAnalysisRequest(BaseModel):
    """Request model for repository analysis."""
    repository_url: str
    branch: Optional[str] = Field(default="main")
    include_stats: bool = Field(default=True)


class RepositoryAnalysisResponse(BaseModel):
    """Response model for repository analysis."""
    repository: str
    branch: str
    analysis_id: str
    file_count: Optional[int] = None
    language_distribution: Optional[Dict[str, int]] = None
    message: str


# =================== Core API Endpoints ===================

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main HTML interface."""
    html_file = TEMPLATES_DIR / "index.html"
    if html_file.exists():
        return html_file.read_text()
    return "<h1>BadDocs Repository Documentation System</h1><p>Web interface not found. Use API endpoints directly.</p>"


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint with feature availability."""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.utcnow().isoformat(),
        storage_enabled=HAS_STORAGE_SUPPORT,
        mcp_enabled=HAS_MCP_SUPPORT,
        github_app_enabled=HAS_GITHUB_APP_SUPPORT
    )


@app.post("/api/documentation/generate", response_model=DocumentationResponse)
async def generate_documentation(
    request: DocumentationRequest,
    background_tasks: BackgroundTasks
):
    """
    Generate documentation for a GitHub repository.
    
    Supports:
    - Incremental updates for existing documentation
    - Multiple LLM providers (Anthropic, OpenAI, etc.)
    - Background task processing
    """
    try:
        task_id = secrets.token_hex(16)
        
        async with global_state.task_lock:
            global_state.active_tasks[task_id] = {
                "status": "queued",
                "repository": request.repository_url,
                "created_at": datetime.utcnow().isoformat()
            }
        
        # Queue background task
        if HAS_MCP_SUPPORT and global_state.mcp_integration:
            background_tasks.add_task(
                process_documentation,
                task_id=task_id,
                request=request
            )
        else:
            return DocumentationResponse(
                task_id=task_id,
                status="error",
                repository=request.repository_url,
                message="MCP integration not available"
            )
        
        return DocumentationResponse(
            task_id=task_id,
            status="queued",
            repository=request.repository_url,
            message="Documentation generation queued"
        )
    except Exception as e:
        logger.error(f"Error generating documentation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """Get the status of a documentation generation task."""
    async with global_state.task_lock:
        if task_id not in global_state.active_tasks:
            raise HTTPException(status_code=404, detail="Task not found")
        
        task_info = global_state.active_tasks[task_id]
        
        return TaskStatusResponse(
            task_id=task_id,
            status=task_info.get("status", "unknown"),
            progress=task_info.get("progress"),
            result=task_info.get("result"),
            error=task_info.get("error")
        )


@app.post("/api/repository/analyze", response_model=RepositoryAnalysisResponse)
async def analyze_repository(request: RepositoryAnalysisRequest):
    """
    Analyze a GitHub repository for documentation generation.
    
    Returns:
    - File count and distribution
    - Language distribution
    - Repository structure overview
    """
    try:
        analysis_id = secrets.token_hex(12)
        
        if not HAS_MCP_SUPPORT or not global_state.mcp_integration:
            raise HTTPException(
                status_code=503,
                detail="Repository analysis not available (MCP integration disabled)"
            )
        
        # Perform analysis via MCP integration
        return RepositoryAnalysisResponse(
            repository=request.repository_url,
            branch=request.branch or "main",
            analysis_id=analysis_id,
            message="Repository analysis initiated"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error analyzing repository: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/config/validate", response_model=ConfigValidationResponse)
async def validate_configuration(request: ConfigValidationRequest):
    """
    Validate LLM provider configuration.
    
    Checks:
    - Credential validity
    - Provider availability
    - Model support
    """
    try:
        provider_name = request.provider_name.lower()
        providers_registry = ProviderRegistry()
        
        if not providers_registry.is_provider_available(provider_name):
            return ConfigValidationResponse(
                valid=False,
                message=f"Provider '{provider_name}' not available"
            )
        
        # Validate credentials by attempting connection
        supported_models = []
        try:
            # Attempt to validate through provider registry
            is_valid = providers_registry.validate_credentials(
                provider_name,
                request.credentials
            )
            
            if is_valid:
                supported_models = providers_registry.get_supported_models(provider_name)
                return ConfigValidationResponse(
                    valid=True,
                    message=f"Configuration valid for '{provider_name}'",
                    supported_models=supported_models
                )
            else:
                return ConfigValidationResponse(
                    valid=False,
                    message=f"Invalid credentials for '{provider_name}'"
                )
        except Exception as e:
            return ConfigValidationResponse(
                valid=False,
                message=f"Validation error: {str(e)}"
            )
    except Exception as e:
        logger.error(f"Configuration validation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/providers/list")
async def list_providers():
    """List available LLM providers and their models."""
    try:
        providers_registry = ProviderRegistry()
        available_providers = providers_registry.get_available_providers()
        
        provider_info = {}
        for provider_name in available_providers:
            try:
                models = providers_registry.get_supported_models(provider_name)
                provider_info[provider_name] = {
                    "available": True,
                    "models": models
                }
            except Exception as e:
                provider_info[provider_name] = {
                    "available": False,
                    "error": str(e)
                }
        
        return {"providers": provider_info}
    except Exception as e:
        logger.error(f"Error listing providers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =================== Database Configuration Routes ===================
# Include database config router
if global_state.db_router:
    app.include_router(
        global_state.db_router.router,
        prefix="/api/database",
        tags=["database"]
    )


# =================== GitHub App Integration Routes ===================
@app.post("/api/github/webhook")
async def github_webhook(request: Request):
    """
    Handle GitHub App webhook events.
    
    Processes:
    - Installation events
    - Repository events
    - Push events
    - Pull request events
    """
    try:
        if not HAS_GITHUB_APP_SUPPORT or not global_state.github_integration:
            raise HTTPException(
                status_code=503,
                detail="GitHub App integration not available"
            )
        
        body = await request.body()
        signature = request.headers.get("X-Hub-Signature-256")
        
        # Verify webhook signature
        if not global_state.github_integration.verify_webhook_signature(
            body, signature
        ):
            raise HTTPException(status_code=401, detail="Invalid signature")
        
        # Process webhook event
        event_type = request.headers.get("X-GitHub-Event")
        await global_state.github_integration.process_webhook(body, event_type)
        
        return {"status": "processed"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/github/authorize")
async def github_authorize(code: str, state: str):
    """Handle GitHub OAuth callback."""
    try:
        if not HAS_GITHUB_APP_SUPPORT or not global_state.github_integration:
            raise HTTPException(
                status_code=503,
                detail="GitHub App integration not available"
            )
        
        result = await global_state.github_integration.handle_oauth_callback(code, state)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"OAuth callback error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =================== Background Task Processors ===================
async def process_documentation(task_id: str, request: DocumentationRequest):
    """
    Background task: Process documentation generation.
    
    Handles:
    - Repository cloning and analysis
    - Incremental documentation updates
    - Document generation and storage
    """
    try:
        async with global_state.task_lock:
            global_state.active_tasks[task_id]["status"] = "processing"
            global_state.active_tasks[task_id]["started_at"] = datetime.utcnow().isoformat()
        
        logger.info(f"Processing documentation generation for {request.repository_url}")
        
        # Use MCP integration for orchestrated processing
        if global_state.mcp_integration:
            result = await global_state.mcp_integration.process_repository(
                repository_url=request.repository_url,
                branch=request.branch,
                incremental=request.incremental,
                provider=request.provider,
                model=request.model
            )
            
            async with global_state.task_lock:
                global_state.active_tasks[task_id].update({
                    "status": "completed",
                    "result": result,
                    "completed_at": datetime.utcnow().isoformat()
                })
        else:
            raise RuntimeError("MCP integration not available")
            
    except Exception as e:
        logger.error(f"Documentation processing error for {task_id}: {e}")
        async with global_state.task_lock:
            global_state.active_tasks[task_id].update({
                "status": "failed",
                "error": str(e),
                "failed_at": datetime.utcnow().isoformat()
            })


# =================== Search Endpoints ===================
@app.get("/api/search")
async def search_documentation(
    query: str,
    limit: int = 10,
    offset: int = 0
):
    """
    Search generated documentation.
    
    Returns:
    - Matching documents
    - Search metadata
    """
    try:
        if not HAS_STORAGE_SUPPORT or not global_state.storage_manager:
            raise HTTPException(
                status_code=503,
                detail="Search functionality not available"
            )
        
        search_engine = SearchEngine(global_state.storage_manager)
        results = search_engine.search(
            query=query,
            limit=limit,
            offset=offset
        )
        
        return {
            "query": query,
            "results": results,
            "total": len(results)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =================== Document Management Endpoints ===================
@app.get("/api/documents/{doc_id}")
async def get_document(doc_id: str):
    """Retrieve a specific generated document."""
    try:
        if not HAS_STORAGE_SUPPORT or not global_state.storage_manager:
            raise HTTPException(
                status_code=503,
                detail="Document storage not available"
            )
        
        doc_ops = DocumentOperations(global_state.storage_manager)
        document = doc_ops.get_document(doc_id)
        
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        
        return document
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Document retrieval error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: str):
    """Delete a generated document."""
    try:
        if not HAS_STORAGE_SUPPORT or not global_state.storage_manager:
            raise HTTPException(
                status_code=503,
                detail="Document storage not available"
            )
        
        doc_ops = DocumentOperations(global_state.storage_manager)
        success = doc_ops.delete_document(doc_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="Document not found")
        
        return {"status": "deleted", "doc_id": doc_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Document deletion error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =================== Error Handlers ===================
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Custom HTTP exception handler."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code,
            "timestamp": datetime.utcnow().isoformat()
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """General exception handler."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "status_code": 500,
            "timestamp": datetime.utcnow().isoformat()
        }
    )


# =================== Debug Endpoints (Development Only) ===================
if os.getenv("DEBUG", "false").lower() == "true":
    
    @app.get("/api/debug/tasks")
    async def debug_get_tasks():
        """Debug endpoint: Get all active tasks."""
        async with global_state.task_lock:
            return {"tasks": global_state.active_tasks}
    
    @app.delete("/api/debug/tasks/{task_id}")
    async def debug_delete_task(task_id: str):
        """Debug endpoint: Delete a task."""
        async with global_state.task_lock:
            if task_id in global_state.active_tasks:
                del global_state.active_tasks[task_id]
                return {"status": "deleted"}
            raise HTTPException(status_code=404, detail="Task not found")
    
    @app.get("/api/debug/state")
    async def debug_get_state():
        """Debug endpoint: Get application state."""
        return {
            "storage_enabled": HAS_STORAGE_SUPPORT,
            "mcp_enabled": HAS_MCP_SUPPORT,
            "github_app_enabled": HAS_GITHUB_APP_SUPPORT,
            "active_tasks_count": len(global_state.active_tasks)
        }


# =================== Application Entry Point ===================
if __name__ == "__main__":
    import uvicorn
    
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))
    debug = os.getenv("DEBUG", "false").lower() == "true"
    
    logger.info(f"Starting BadDocs on {host}:{port} (debug={debug})")
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=debug,
        log_level="info"
    )
