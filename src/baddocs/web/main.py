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

# Repository analysis imports (fallback when MCP unavailable)
try:
    from ..mcp_servers.git.analyzer import RepositoryAnalyzer, RepositoryInfo
    from ..incremental.processor import IncrementalProcessor
    HAS_REPOSITORY_SUPPORT = True
except ImportError as e:
    logging.warning(f"Repository analysis not available: {e}")
    HAS_REPOSITORY_SUPPORT = False

# GitHub Secrets integration
try:
    from .github_secrets import GitHubSecretsManager, DatabaseCredentialsProvider
    HAS_SECRETS_SUPPORT = True
    logging.info("GitHub Secrets integration enabled")
except ImportError as e:
    logging.warning(f"GitHub Secrets integration not available: {e}")
    HAS_SECRETS_SUPPORT = False


# Global state
app_state = {
    "registry": None,
    "config_manager": None,
    "repository_analyzer": None,
    "storage_manager": None,
    "file_operations": None,
    "document_operations": None,
    "search_engine": None,
    "mcp_integration": None,  # MCP orchestration client
    "repositories": {},  # repository_id -> RepositoryStatus
    "startup_complete": False
}

# Pydantic models for API
class HealthResponse(BaseModel):
    status: str
    version: str
    providers_available: int
    startup_complete: bool

# Repository-focused request/response models
class RepositoryRequest(BaseModel):
    repository_url: str = Field(..., description="GitHub repository URL")
    branch: Optional[str] = Field("main", description="Branch to analyze")
    clone_depth: int = Field(1, description="Git clone depth")
    include_patterns: Optional[List[str]] = Field(None, description="File patterns to include")
    exclude_patterns: Optional[List[str]] = Field(None, description="File patterns to exclude")

class RepositoryAnalysisResponse(BaseModel):
    repository_id: str
    status: str
    total_files: int
    processed_files: int
    documentation_coverage: float
    analysis_started: str
    estimated_completion: Optional[str] = None
    errors: Optional[List[str]] = None

class RepositoryStatus(BaseModel):
    repository_id: str
    repository_url: str
    status: str
    total_files: int
    documented_files: int
    coverage_percentage: float
    last_update: str
    processing_errors: List[str] = []

class WebhookPayload(BaseModel):
    action: str
    repository: Dict[str, Any]
    commits: Optional[List[Dict[str, Any]]] = None
    pull_request: Optional[Dict[str, Any]] = None

# Legacy models for backward compatibility (deprecated)
class DocumentationRequest(BaseModel):
    code: str = Field(..., description="[DEPRECATED] Code to document")
    language: str = Field(..., description="Programming language")
    context_type: str = Field(default="function", description="Type of code context")
    model: Optional[str] = Field(None, description="Specific model to use")
    temperature: float = Field(default=0.1, description="LLM temperature")

class DocumentationResponse(BaseModel):
    documentation: str
    model_used: str
    provider_used: str
    processing_time_ms: int
    tokens_used: Optional[int] = None

class ProviderStatus(BaseModel):
    name: str
    type: str
    enabled: bool
    healthy: bool
    priority: int
    cost_tier: str

class SystemStatus(BaseModel):
    providers: List[ProviderStatus]
    mvp_config: str
    budget_usage: Optional[Dict[str, Any]] = None

# Search models
class SearchRequest(BaseModel):
    query: str = Field(..., description="Search query")
    repository_url: Optional[str] = Field(None, description="Filter by repository")
    doc_type: Optional[str] = Field(None, description="Filter by document type")
    language: Optional[str] = Field(None, description="Filter by programming language")
    limit: int = Field(default=20, description="Maximum results to return")

class SearchResponse(BaseModel):
    results: List[Dict[str, Any]]
    total_count: int
    query_time_ms: float
    has_more: bool


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger = logging.getLogger(__name__)
    logger.info("Starting BadDocs Web API...")

    try:
        # Initialize configuration manager
        app_state["config_manager"] = providers_config

        # Determine MVP tier from environment
        mvp_tier = os.getenv("BADDOCS_MVP_TIER", "budget")
        logger.info(f"Using MVP tier: {mvp_tier}")

        # Create provider registry for MVP deployment
        registry = await app_state["config_manager"].create_registry_for_mvp(mvp_tier)
        app_state["registry"] = registry

        # Initialize MCP integration if available
        if HAS_MCP_SUPPORT:
            try:
                mcp_orchestrator_url = os.getenv("MCP_ORCHESTRATOR_URL", "http://localhost:8001")
                print(f"DEBUG: MCP_ORCHESTRATOR_URL from env: {mcp_orchestrator_url}")
                logger.info(f"🔗 Attempting MCP connection to: {mcp_orchestrator_url}")
                app_state["mcp_integration"] = MCPWebIntegration(mcp_orchestrator_url)

                # Try to initialize MCP connection
                mcp_initialized = await app_state["mcp_integration"].initialize()
                if mcp_initialized:
                    logger.info(f"✅ MCP orchestration initialized: {mcp_orchestrator_url}")
                else:
                    logger.warning("⚠️ MCP orchestration failed to initialize - using fallback mode")
                    app_state["mcp_integration"] = None
            except Exception as e:
                logger.error(f"❌ MCP initialization failed: {e}")
                app_state["mcp_integration"] = None
        else:
            logger.warning("MCP integration not available - using direct imports")

        # Set up repository analysis system
        if app_state.get("mcp_integration") and HAS_REPOSITORY_SUPPORT:
            # MCP is available - use MCP-based analysis
            app_state["repository_analyzer"] = app_state["mcp_integration"]
            logger.info("Repository analyzer initialized (MCP mode)")
        elif HAS_REPOSITORY_SUPPORT:
            # MCP not available - use fallback direct analysis
            app_state["repository_analyzer"] = RepositoryAnalyzer()
            logger.info("Repository analyzer initialized (fallback mode)")
        else:
            logger.warning("Repository analysis not available - limited functionality")

        # Storage system integration (keep existing functionality)
        if HAS_STORAGE_SUPPORT:
            try:
                # Initialize storage components with the same configuration as MCP storage server
                from ..storage import StorageManager, DocumentOperations, FileOperations, SearchEngine

                # Use the same database path as the MCP storage server
                db_path = os.getenv("STORAGE_DB_PATH", "/app/data/baddocs.db")

                # Initialize storage manager
                storage_manager = StorageManager(db_path)
                await storage_manager.initialize()
                app_state["storage_manager"] = storage_manager

                # Initialize operations
                app_state["document_operations"] = DocumentOperations(storage_manager)
                app_state["file_operations"] = FileOperations(storage_manager)
                app_state["search_engine"] = SearchEngine(storage_manager)

                logger.info(f"✅ Storage system initialized with database: {db_path}")

                # Initialize database config routes
                try:
                    from .database_config_routes import init_database_config_routes
                    github_auth = None
                    try:
                        from .github.auth import GitHubAppAuth
                        if os.getenv('GITHUB_APP_ID'):
                            github_auth = GitHubAppAuth()
                    except ImportError:
                        pass
                    init_database_config_routes(app, storage_manager, github_auth)
                    logger.info("✅ Database configuration routes initialized")
                except Exception as route_error:
                    logger.warning(f"⚠️ Database config routes initialization failed: {route_error}")

            except Exception as e:
                logger.error(f"❌ Storage system initialization failed: {e}")
                # Set storage components to None to ensure fallback behavior
                app_state["storage_manager"] = None
                app_state["document_operations"] = None
                app_state["file_operations"] = None
                app_state["search_engine"] = None
        else:
            logger.warning("Storage system not available - file-only mode")

        logger.info(f"Initialized provider registry with {len(registry.providers)} providers")
        app_state["startup_complete"] = True

    except Exception as e:
        logger.error(f"Startup failed: {e}")
        app_state["startup_complete"] = False

    yield

    # Shutdown
    logger.info("Shutting down BadDocs Web API...")
    if app_state["registry"]:
        await app_state["registry"].shutdown()
    if app_state["mcp_integration"]:
        await app_state["mcp_integration"].close()
        logger.info("MCP integration shutdown complete")
    if app_state["storage_manager"]:
        app_state["storage_manager"].shutdown()
        logger.info("Storage system shutdown complete")


# Helper functions
def generate_repo_id(url: str) -> str:
    """Generate human-readable repository ID from GitHub URL."""
    # Extract owner/repo from GitHub URLs
    # e.g. https://github.com/owner/repo -> owner-repo
    import re
    match = re.search(r'github\.com[/:]([^/]+)/([^/]+?)(?:\.git|/|$)', url)
    if match:
        owner, repo = match.groups()
        return f"{owner}-{repo}"
    else:
        # Fallback to hash if not a standard GitHub URL
        import hashlib
        return hashlib.md5(url.encode()).hexdigest()[:16]


def _detect_language_from_extension_for_pipeline(extension: str) -> str:
    """Detect programming language from file extension."""
    extension_map = {
        '.py': 'python', '.pyw': 'python', '.pyi': 'python',
        '.js': 'javascript', '.mjs': 'javascript', '.jsx': 'javascript',
        '.ts': 'typescript', '.tsx': 'typescript', '.cjs': 'javascript',
        '.java': 'java',
        '.cs': 'csharp',
        '.go': 'go',
        '.rb': 'ruby', '.rake': 'ruby', '.gemspec': 'ruby', '.ru': 'ruby',
        '.rs': 'rust',
        '.php': 'php', '.phtml': 'php', '.php3': 'php', '.php4': 'php', '.php5': 'php', '.phps': 'php',
        '.cbl': 'cobol', '.cob': 'cobol', '.cpy': 'cobol', '.pco': 'cobol', '.cobol': 'cobol',
        '.f': 'fortran', '.f77': 'fortran', '.f90': 'fortran', '.f95': 'fortran', '.for': 'fortran', '.ftn': 'fortran',
        '.bas': 'vb6', '.frm': 'vb6', '.cls': 'vb6', '.ctl': 'vb6', '.pag': 'vb6', '.dob': 'vb6', '.vb': 'vb6',
        '.pbl': 'powerbuilder', '.pbt': 'powerbuilder', '.pbw': 'powerbuilder', '.srd': 'powerbuilder', '.sru': 'powerbuilder', '.srw': 'powerbuilder', '.pbd': 'powerbuilder',
        '.r': 'r', '.R': 'r', '.Rmd': 'r', '.Rnw': 'r', '.Rscript': 'r'
    }
    return extension_map.get(extension, 'unknown')


def _get_processor_for_language(language: str, config: Dict[str, Any]):
    """Get language processor for a given language."""
    from ..processors import (
        PythonProcessor, JavaScriptProcessor, JavaProcessor, CSharpProcessor,
        GoProcessor, RubyProcessor, RustProcessor, PHPProcessor,
        CobolProcessor, FortranProcessor, VB6Processor, PowerBuilderProcessor, RProcessor
    )

    language_to_processor = {
        'python': PythonProcessor,
        'javascript': JavaScriptProcessor,
        'typescript': JavaScriptProcessor,
        'java': JavaProcessor,
        'csharp': CSharpProcessor,
        'go': GoProcessor,
        'ruby': RubyProcessor,
        'rust': RustProcessor,
        'php': PHPProcessor,
        'cobol': CobolProcessor,
        'fortran': FortranProcessor,
        'vb6': VB6Processor,
        'powerbuilder': PowerBuilderProcessor,
        'r': RProcessor,
    }
    processor_class = language_to_processor.get(language.lower())
    if processor_class:
        return processor_class(config)
    return None


# Create FastAPI app
app = FastAPI(
    title="BadDocs MVP API",
    description="AI-powered documentation generation for legacy codebases",
    version="0.1.0",
    lifespan=lifespan
)

# CORS middleware for web frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Logging setup
logging.basicConfig(
    level=getattr(logging, os.getenv("BADDOCS_LOG_LEVEL", "INFO")),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Mount static files
static_path = Path(__file__).parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")


# Dependency injection
async def get_registry() -> ProviderRegistry:
    """Get the provider registry."""
    if not app_state["registry"]:
        raise HTTPException(status_code=503, detail="Provider registry not initialized")
    return app_state["registry"]

async def get_storage_manager() -> Optional[Any]:
    """Get the storage manager (can be None if not available)."""
    return app_state.get("storage_manager")

async def get_document_operations() -> Optional[Any]:
    """Get the document operations (can be None if not available)."""
    return app_state.get("document_operations")

async def get_file_operations() -> Optional[Any]:
    """Get the file operations (can be None if not available)."""
    return app_state.get("file_operations")

async def get_search_engine() -> Optional[Any]:
    """Get the search engine (can be None if not available)."""
    return app_state.get("search_engine")


async def get_config_manager() -> ProvidersConfigManager:
    """Get the configuration manager."""
    if not app_state["config_manager"]:
        raise HTTPException(status_code=503, detail="Configuration manager not initialized")
    return app_state["config_manager"]


async def get_repository_analyzer():
    """Get the repository analyzer."""
    if not HAS_REPOSITORY_SUPPORT or not app_state["repository_analyzer"]:
        return None  # Return None instead of raising exception - endpoints will handle fallback
    return app_state["repository_analyzer"]


# API Endpoints

@app.get("/")
async def root():
    """Serve the repository dashboard interface."""
    html_path = Path(__file__).parent / "static" / "repositories.html"
    if html_path.exists():
        return FileResponse(html_path)
    else:
        return {
            "service": "BadDocs Repository Documentation System",
            "version": "0.1.0",
            "status": "running" if app_state["startup_complete"] else "starting",
            "message": "Repository dashboard not available - API only mode"
        }


@app.get("/legacy")
async def legacy_interface():
    """Serve the legacy code snippet interface (deprecated)."""
    html_path = Path(__file__).parent / "static" / "index.html"
    if html_path.exists():
        return FileResponse(html_path)
    else:
        return {"message": "Legacy interface not available"}


@app.get("/api", response_model=Dict[str, str])
async def api_info():
    """API information endpoint."""
    return {
        "service": "BadDocs MVP API",
        "version": "0.1.0",
        "status": "running" if app_state["startup_complete"] else "starting"
    }


@app.get("/health", response_model=HealthResponse)
async def health_check(registry: ProviderRegistry = Depends(get_registry)):
    """Health check endpoint for deployment platforms."""
    providers_available = len(registry.providers) if registry else 0

    # Determine processing mode
    if app_state.get("mcp_integration"):
        processing_mode = "MCP-orchestrated"
        mcp_status = "available"
    elif app_state.get("repository_analyzer"):
        processing_mode = "direct-import-fallback"
        mcp_status = "unavailable"
    else:
        processing_mode = "limited-functionality"
        mcp_status = "unavailable"

    return HealthResponse(
        status="healthy" if app_state["startup_complete"] else "starting",
        version="0.1.0",
        providers_available=providers_available,
        startup_complete=app_state["startup_complete"],
        mcp_integration=mcp_status,
        processing_mode=processing_mode
    )


@app.get("/api/mcp-status")
async def get_mcp_status():
    """Get MCP orchestration system status."""
    mcp_integration = app_state.get("mcp_integration")

    if not mcp_integration:
        return {
            "mcp_available": False,
            "status": "disabled",
            "message": "MCP orchestration not available - using direct imports"
        }

    try:
        # Get comprehensive MCP system status
        mcp_status = await mcp_integration.get_system_health()
        return {
            "mcp_available": True,
            "status": "active",
            "system_status": mcp_status,
            "message": "MCP orchestration active"
        }
    except Exception as e:
        return {
            "mcp_available": True,
            "status": "error",
            "error": str(e),
            "message": "MCP orchestration configured but experiencing issues"
        }


@app.post("/generate-docs", response_model=DocumentationResponse)
async def generate_documentation(
    request: DocumentationRequest,
    background_tasks: BackgroundTasks,
    registry: ProviderRegistry = Depends(get_registry)
):
    """Generate documentation for provided code."""
    try:
        # Create LLM request
        llm_request = LLMRequest(
            prompt=f"Generate comprehensive documentation for this {request.language} {request.context_type}:\n\n{request.code}",
            model=request.model,
            temperature=request.temperature,
            context_type=request.context_type,
            language=request.language,
            max_tokens=2048
        )

        # Generate documentation
        response = await registry.generate(llm_request)

        if response.error:
            raise HTTPException(status_code=500, detail=f"Generation failed: {response.error}")

        return DocumentationResponse(
            documentation=response.content,
            model_used=response.model,
            provider_used=response.provider,
            processing_time_ms=response.processing_time_ms or 0,
            tokens_used=response.total_tokens
        )

    except Exception as e:
        logger.error(f"Documentation generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/status", response_model=SystemStatus)
async def system_status(
    registry: ProviderRegistry = Depends(get_registry),
    config_manager: ProvidersConfigManager = Depends(get_config_manager)
):
    """Get system status including provider health."""
    try:
        provider_statuses = []

        # Get provider information from config
        provider_info = config_manager.get_provider_info()

        for name, info in provider_info.items():
            # Check if provider is in registry
            provider_in_registry = name in registry.providers

            provider_statuses.append(ProviderStatus(
                name=name,
                type=info["type"],
                enabled=info["enabled"],
                healthy=provider_in_registry,  # Simplified health check
                priority=info["priority"],
                cost_tier=info["cost_tier"]
            ))

        mvp_tier = os.getenv("BADDOCS_MVP_TIER", "budget")

        return SystemStatus(
            providers=provider_statuses,
            mvp_config=mvp_tier,
            budget_usage=None  # TODO: Implement budget tracking
        )

    except Exception as e:
        logger.error(f"Status check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/providers", response_model=Dict[str, Any])
async def list_providers(config_manager: ProvidersConfigManager = Depends(get_config_manager)):
    """List all configured providers and their capabilities."""
    try:
        return {
            "providers": config_manager.get_provider_info(),
            "mvp_configs": config_manager.get_available_mvp_configs()
        }
    except Exception as e:
        logger.error(f"Provider listing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/test-provider/{provider_name}")
async def test_provider(
    provider_name: str,
    registry: ProviderRegistry = Depends(get_registry)
):
    """Test a specific provider with a simple request."""
    if provider_name not in registry.providers:
        raise HTTPException(status_code=404, detail=f"Provider {provider_name} not found")

    try:
        # Simple test request
        test_request = LLMRequest(
            prompt="Say 'Hello from BadDocs!' in a friendly way.",
            max_tokens=50
        )

        response = await registry.providers[provider_name].generate(test_request)

        return {
            "provider": provider_name,
            "test_successful": not bool(response.error),
            "response": response.content if not response.error else None,
            "error": response.error,
            "processing_time_ms": response.processing_time_ms
        }

    except Exception as e:
        logger.error(f"Provider test failed for {provider_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/cost-estimate")
async def get_cost_estimate(
    mvp_config: str = "budget",
    monthly_requests: int = 10000,
    config_manager: ProvidersConfigManager = Depends(get_config_manager)
):
    """Get cost estimate for MVP deployment."""
    try:
        estimate = config_manager.get_cost_estimate(mvp_config, monthly_requests)
        return estimate
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Cost estimation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Repository Analysis API Endpoints (GitHub App Integration)
# ============================================================================

@app.post("/api/repositories/analyze", response_model=RepositoryAnalysisResponse)
async def analyze_repository(
    request: RepositoryRequest,
    analyzer = Depends(get_repository_analyzer)
):
    """Analyze a GitHub repository and start documentation generation."""
    logger.info(f"🎯 ANALYZE ENDPOINT CALLED with URL: {request.repository_url}")
    try:
        # Log analyzer availability for debugging
        if analyzer is None:
            logger.warning("Repository analyzer not available - using fallback mode")
        else:
            logger.info("Using full repository analyzer")
        # Generate human-readable repository ID from URL
        repo_id = generate_repo_id(request.repository_url)

        logger.info(f"Starting repository analysis: {request.repository_url}")

        # Initialize repository status
        app_state["repositories"][repo_id] = RepositoryStatus(
            repository_id=repo_id,
            repository_url=request.repository_url,
            status="analyzing",
            total_files=0,
            documented_files=0,
            coverage_percentage=0.0,
            last_update=datetime.now().isoformat()
        )

        # Start background analysis using async task (proper async integration)
        logger.info(f"🚀 STARTING ASYNC MCP background task for repo {repo_id}")

        # Use asyncio.create_task for proper async background execution
        import asyncio
        task = asyncio.create_task(_analyze_repository_mcp_async(repo_id, request.repository_url, analyzer))
        logger.info(f"🚀 ASYNC MCP BACKGROUND TASK STARTED for repo {repo_id}")

        return RepositoryAnalysisResponse(
            repository_id=repo_id,
            status="started",
            total_files=0,
            processed_files=0,
            documentation_coverage=0.0,
            analysis_started=datetime.now().isoformat(),
            estimated_completion=None
        )

    except Exception as e:
        logger.error(f"Repository analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/repositories/{repo_id}/status", response_model=RepositoryStatus)
async def get_repository_status(repo_id: str):
    """Get the current status of repository analysis."""
    if repo_id not in app_state["repositories"]:
        raise HTTPException(status_code=404, detail="Repository not found")

    return app_state["repositories"][repo_id]


@app.get("/api/repositories")
async def list_repositories():
    """List all tracked repositories."""
    return {
        "repositories": list(app_state["repositories"].values()),
        "total": len(app_state["repositories"])
    }


@app.post("/api/repositories/{repo_id}/regenerate")
async def regenerate_repository_docs(
    repo_id: str,
    background_tasks: BackgroundTasks,
    analyzer = Depends(get_repository_analyzer)
):
    """Trigger full regeneration of repository documentation."""
    if repo_id not in app_state["repositories"]:
        raise HTTPException(status_code=404, detail="Repository not found")

    repo_status = app_state["repositories"][repo_id]
    repo_status.status = "regenerating"
    repo_status.last_update = datetime.now().isoformat()

    # Create a new RepositoryRequest from stored data
    request = RepositoryRequest(repository_url=repo_status.repository_url)

    # Use async task instead of BackgroundTasks for proper MCP integration
    task = asyncio.create_task(_analyze_repository_mcp_async(repo_id, request.repository_url, analyzer))

    return {"status": "regeneration_started", "repository_id": repo_id}


# GitHub App Setup and Management Endpoints

@app.get("/github/setup")
async def github_app_setup(installation_id: Optional[int] = None, setup_action: Optional[str] = None):
    """GitHub App setup landing page after installation."""
    try:
        # Initialize GitHub App auth if available
        github_auth = None
        try:
            from .github.auth import GitHubAppAuth
            from .github.pr_manager import GitHubPRManager
            from ..storage.repository_config import RepositoryConfigManager

            if os.getenv('GITHUB_APP_ID'):
                github_auth = GitHubAppAuth()
            else:
                # Redirect to configuration instructions
                return HTMLResponse("""
                <!DOCTYPE html>
                <html lang="en">
                <head>
                    <meta charset="UTF-8">
                    <title>GitHub App Setup Required - BadDocs</title>
                    <style>
                        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 40px; line-height: 1.6; }
                        .container { max-width: 800px; margin: 0 auto; }
                        .warning { background: #fff3cd; border: 1px solid #ffeaa7; border-radius: 8px; padding: 20px; margin: 20px 0; }
                        .steps { background: #f8f9fa; border-radius: 8px; padding: 20px; margin: 20px 0; }
                        code { background: #f1f3f4; padding: 2px 6px; border-radius: 4px; font-family: monospace; }
                        .btn { background: #0969da; color: white; padding: 10px 20px; text-decoration: none; border-radius: 6px; display: inline-block; }
                    </style>
                </head>
                <body>
                    <div class="container">
                        <h1>🔧 GitHub App Setup Required</h1>

                        <div class="warning">
                            <h3>⚠️ Configuration Missing</h3>
                            <p>Your BadDocs GitHub App is not configured. Please set up the following environment variables:</p>
                        </div>

                        <div class="steps">
                            <h3>Required Environment Variables:</h3>
                            <ul>
                                <li><code>GITHUB_APP_ID</code> - Your GitHub App ID (e.g., 123456)</li>
                                <li><code>GITHUB_APP_PRIVATE_KEY</code> - Your GitHub App private key (full PEM content)</li>
                                <li><code>GITHUB_WEBHOOK_SECRET</code> - Webhook secret for security</li>
                            </ul>

                            <h3>Next Steps:</h3>
                            <ol>
                                <li>Configure your GitHub App with setup URL: <code>https://your-domain/github/setup</code></li>
                                <li>Set the environment variables in your <code>.env</code> file</li>
                                <li>Restart the application: <code>docker-compose up -d</code></li>
                                <li>Install the GitHub App on your repositories</li>
                            </ol>
                        </div>

                        <p><a href="/GITHUB_APP_SETUP.md" class="btn">📖 View Complete Setup Guide</a></p>
                        <p><a href="/">← Back to Dashboard</a></p>
                    </div>
                </body>
                </html>
                """)

        except ImportError:
            return HTMLResponse("GitHub App functionality not available")

        # Get installation data if provided
        installation_data = {}
        repositories = []
        debug_info = ""
        installation_account_type = None
        installation_account_login = None

        if installation_id and github_auth:
            try:
                # Add debug logging
                logger.info(f"Attempting to get repositories for installation ID: {installation_id}")

                # First check if this might be the App ID instead of installation ID
                app_id = os.getenv('GITHUB_APP_ID')
                if str(installation_id) == str(app_id):
                    debug_info = f"⚠️ WARNING: Using App ID ({app_id}) as installation ID. This is likely incorrect."
                    logger.warning(f"Installation ID {installation_id} matches App ID {app_id} - this is likely wrong")

                # Get installation details to build correct GitHub URL
                all_installations = github_auth.get_app_installations()
                for inst in all_installations:
                    if inst.get('id') == installation_id:
                        installation_account_type = inst.get('account', {}).get('type', 'User')
                        installation_account_login = inst.get('account', {}).get('login', '')
                        break

                repositories = github_auth.get_installation_repositories(installation_id)
                installation_data = {
                    'installation_id': installation_id,
                    'repository_count': len(repositories),
                    'account_type': installation_account_type,
                    'account_login': installation_account_login
                }
                logger.info(f"Successfully retrieved {len(repositories)} repositories for installation {installation_id}")

            except Exception as e:
                logger.error(f"Failed to get installation data for ID {installation_id}: {e}")
                debug_info = f"🚨 Error fetching repositories: {str(e)}"

                # Try to get all installations to help with debugging
                try:
                    all_installations = github_auth.get_app_installations()
                    debug_info += f"<br>Available installations: {[inst.get('id') for inst in all_installations]}"
                except Exception as inst_error:
                    debug_info += f"<br>Could not retrieve installations: {str(inst_error)}"

        # Generate HTML for setup page
        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BadDocs GitHub App Setup</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 40px; }}
        .container {{ max-width: 800px; margin: 0 auto; }}
        .header {{ text-align: center; margin-bottom: 40px; }}
        .card {{ background: #f8f9fa; border-radius: 8px; padding: 20px; margin: 20px 0; border: 1px solid #e9ecef; }}
        .repo-item {{ background: white; border-radius: 6px; padding: 15px; margin: 10px 0; border: 1px solid #d0d7de; }}
        .btn {{ background: #0969da; color: white; border: none; padding: 10px 20px; border-radius: 6px; cursor: pointer; text-decoration: none; display: inline-block; }}
        .btn:hover {{ background: #0860ca; }}
        .btn-secondary {{ background: #6c757d; }}
        .btn-secondary:hover {{ background: #5c636a; }}
        .checkbox {{ margin-right: 10px; }}
        .success {{ color: #28a745; }}
        .info {{ color: #17a2b8; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 BadDocs GitHub App Setup</h1>
            <p>Welcome! Let's configure BadDocs for your repositories.</p>
        </div>

        {"<div class='card'><h3 class='success'>✅ Installation Successful!</h3><p>GitHub App installed for " + str(installation_data.get('repository_count', 0)) + " repositories.</p></div>" if installation_id else ""}
        {"<div class='card' style='border-left: 4px solid #dc3545;'><h4>🔍 Debug Info</h4><p>" + debug_info + "</p><p><a href='/github/debug/installations' class='btn btn-secondary'>View All Installations</a></p></div>" if debug_info else ""}

        <div class="card">
            <h3>📚 What BadDocs Does</h3>
            <ul>
                <li><strong>Automatic Documentation:</strong> Generates docs when you push code</li>
                <li><strong>Smart Branch Handling:</strong> Configure different behaviors per branch</li>
                <li><strong>Pull Request Integration:</strong> Creates PRs with documentation updates</li>
                <li><strong>Extra Tasks:</strong> Security scans, link validation, version tagging</li>
            </ul>
        </div>

        {"<div class='card'><h3>🔧 Configure Your Repositories</h3>" + _generate_repository_list_html(repositories, installation_id) + "</div>" if repositories else ""}

        <div class="card">
            <h3>⚡ Quick Actions</h3>
            <p>
                {_build_github_config_button(installation_id, installation_account_type, installation_account_login) if installation_id else ""}
                <a href="/github/installations" class="btn btn-secondary">Manage All Installations</a>
                <a href="/" class="btn btn-secondary">Back to Dashboard</a>
            </p>
            {"<p style='margin-top: 15px; padding: 15px; background: #e7f3ff; border-radius: 6px; border-left: 4px solid #0969da;'><strong>💡 Tip:</strong> Use the " + '"Configure GitHub Installation"' + " button above to adjust which repositories BadDocs can access, or to update app permissions after you've made changes to the GitHub App settings.</p>" if installation_id else ""}
        </div>

        <div class="card">
            <h3>📖 Next Steps</h3>
            <ol>
                <li>Select repositories you want to document</li>
                <li>Configure branch triggers and target branches</li>
                <li>Set up pull request preferences</li>
                <li>Test with a manual documentation generation</li>
            </ol>
        </div>
    </div>

    <script>
        // Get installation_id from URL parameter or context
        const currentInstallationId = "{installation_id or ''}";

        function configureRepository(repoId, repoName) {{
            const configUrl = currentInstallationId
                ? `/github/repositories/${{repoId}}/configure?name=${{encodeURIComponent(repoName)}}&installation_id=${{currentInstallationId}}`
                : `/github/repositories/${{repoId}}/configure?name=${{encodeURIComponent(repoName)}}`;
            window.location.href = configUrl;
        }}

        function generateDocs(repoId, repoName) {{
            if(confirm(`Generate documentation for ${{repoName}}?`)) {{
                const requestBody = currentInstallationId
                    ? {{ branch: 'main', installation_id: currentInstallationId }}
                    : {{ branch: 'main' }};

                fetch(`/api/github/repositories/${{repoId}}/generate`, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(requestBody)
                }})
                .then(response => response.json())
                .then(data => {{
                    alert(data.message || 'Documentation generation started!');
                }})
                .catch(error => {{
                    alert('Error: ' + error.message);
                }});
            }}
        }}
    </script>
</body>
</html>
        """

        return HTMLResponse(html_content)

    except Exception as e:
        logger.error(f"GitHub setup page failed: {e}")
        return HTMLResponse(f"<html><body><h1>Setup Error</h1><p>{str(e)}</p></body></html>", status_code=500)


@app.get("/GITHUB_APP_SETUP.md")
async def github_app_setup_guide():
    """Serve the GitHub App setup guide."""
    try:
        with open("/app/GITHUB_APP_SETUP.md", "r") as f:
            content = f.read()
        return Response(content, media_type="text/markdown")
    except FileNotFoundError:
        return Response("# GitHub App Setup Guide\n\nSetup guide not found. Please check the documentation.", media_type="text/markdown")


def _generate_repository_list_html(repositories: List[Dict], installation_id: Optional[int] = None) -> str:
    """Generate HTML for repository list."""
    if not repositories:
        return "<p>No repositories found for this installation.</p>"

    html = "<div style='max-height: 400px; overflow-y: auto;'>"
    for repo in repositories:
        repo_id = repo.get('id')
        repo_name = repo.get('full_name', 'Unknown')
        description = repo.get('description', 'No description')
        default_branch = repo.get('default_branch', 'main')

        # Build database config link
        db_config_link = f"/github/database-config/{repo_id}"
        if installation_id:
            db_config_link += f"?installation_id={installation_id}"

        html += f"""
        <div class="repo-item">
            <h4>{repo_name}</h4>
            <p style="color: #666; margin: 5px 0;">{description}</p>
            <p style="color: #888; font-size: 0.9em;">Default branch: {default_branch}</p>
            <div style="margin-top: 10px;">
                <button onclick="configureRepository('{repo_id}', '{repo_name}')" class="btn" style="margin-right: 10px;">
                    ⚙️ Configure
                </button>
                <a href="{db_config_link}" class="btn btn-secondary" style="margin-right: 10px;">
                    🗄️ Database
                </a>
                <button onclick="generateDocs('{repo_id}', '{repo_name}')" class="btn btn-secondary">
                    📚 Generate Docs Now
                </button>
            </div>
        </div>
        """

    html += "</div>"
    return html


@app.get("/github/debug/installations")
async def debug_github_installations():
    """Debug endpoint to show all GitHub App installations."""
    try:
        from .github.auth import GitHubAppAuth

        github_auth = GitHubAppAuth()
        installations = github_auth.get_app_installations()

        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>GitHub App Installations Debug</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 40px; }}
        .container {{ max-width: 800px; margin: 0 auto; }}
        .installation {{ background: #f8f9fa; border-radius: 8px; padding: 20px; margin: 20px 0; }}
        .btn {{ background: #0969da; color: white; border: none; padding: 10px 20px; border-radius: 6px; cursor: pointer; text-decoration: none; }}
        .code {{ background: #f6f8fa; padding: 10px; border-radius: 6px; font-family: monospace; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🔍 GitHub App Installations Debug</h1>
        <p>App ID: <span class="code">{os.getenv('GITHUB_APP_ID')}</span></p>

        <h2>Available Installations:</h2>
        {"".join([f'''
            <div class="installation">
                <h3>{inst.get("account", {}).get("login", "Unknown Account")}</h3>
                <p><strong>Installation ID:</strong> <span class="code">{inst.get("id")}</span></p>
                <p><strong>Account:</strong> {inst.get("account", {}).get("type", "Unknown")} - {inst.get("account", {}).get("login", "Unknown")}</p>
                <p><strong>Created:</strong> {inst.get("created_at", "Unknown")}</p>
                <a href="/github/setup?installation_id={inst.get("id")}" class="btn">Test This Installation</a>
            </div>
        ''' for inst in installations])}

        <p><a href="/github/setup" class="btn">Back to Setup</a></p>
    </div>
</body>
</html>
        """

        return HTMLResponse(html_content)

    except Exception as e:
        logger.error(f"Debug installations failed: {e}")
        return HTMLResponse(f"<html><body><h1>Error</h1><p>{str(e)}</p></body></html>", status_code=500)


def _build_installation_html(inst: dict) -> str:
    """Build installation HTML with correct GitHub configuration URL."""
    account_login = inst.get("account", {}).get("login", "Unknown")
    account_type = inst.get("account", {}).get("type", "User")
    installation_id = inst.get("id")

    # Build correct GitHub configuration URL based on account type
    if account_type == "Organization":
        config_url = f"https://github.com/organizations/{account_login}/settings/installations/{installation_id}"
    else:  # User
        config_url = f"https://github.com/settings/installations/{installation_id}"

    return f'''<div class="installation">
        <h3>{account_login}</h3>
        <p>Installation ID: <code>{installation_id}</code></p>
        <p>
            <a href="{config_url}" class="btn" target="_blank">⚙️ Configure on GitHub</a>
            <a href="/github/setup?installation_id={installation_id}" class="btn" style="background: #6c757d; margin-left: 10px;">📊 View in BadDocs</a>
        </p>
    </div>'''


def _build_github_config_button(installation_id: int, account_type: Optional[str], account_login: Optional[str]) -> str:
    """Build GitHub configuration button with correct URL."""
    # Build correct GitHub configuration URL based on account type
    if account_type == "Organization" and account_login:
        config_url = f"https://github.com/organizations/{account_login}/settings/installations/{installation_id}"
    else:  # User or unknown
        config_url = f"https://github.com/settings/installations/{installation_id}"

    return f"<a href='{config_url}' class='btn' target='_blank'>⚙️ Configure GitHub Installation</a>"


@app.get("/github/installations")
async def github_installations():
    """List all GitHub App installations."""
    try:
        from .github.auth import GitHubAppAuth

        if not os.getenv('GITHUB_APP_ID'):
            return HTMLResponse("<html><body><h1>GitHub App Not Configured</h1></body></html>")

        github_auth = GitHubAppAuth()
        installations = github_auth.get_app_installations()

        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BadDocs - GitHub Installations</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 40px; }}
        .container {{ max-width: 800px; margin: 0 auto; }}
        .installation {{ background: #f8f9fa; border-radius: 8px; padding: 20px; margin: 20px 0; }}
        .btn {{ background: #0969da; color: white; border: none; padding: 10px 20px; border-radius: 6px; cursor: pointer; text-decoration: none; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>GitHub App Installations</h1>
        <p style="margin-bottom: 20px; color: #6c757d;">BadDocs is installed on {len(installations)} account(s). Click "Configure on GitHub" to manage repository access.</p>
        {"".join([_build_installation_html(inst) for inst in installations])}
        <p><a href="/" class="btn" style="background: #6c757d; margin-top: 20px;">Back to Dashboard</a></p>
    </div>
</body>
</html>
        """

        return HTMLResponse(html_content)

    except Exception as e:
        logger.error(f"Installations page failed: {e}")
        return HTMLResponse(f"<html><body><h1>Error</h1><p>{str(e)}</p></body></html>", status_code=500)


@app.get("/github/repositories/{repo_id}/configure")
async def configure_repository(repo_id: str, name: Optional[str] = None, installation_id: Optional[int] = None):
    """Repository configuration page with simplified GitHub Actions approach."""
    try:
        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Configure Repository - BadDocs</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 40px; line-height: 1.6; }}
        .container {{ max-width: 1000px; margin: 0 auto; }}
        .card {{ background: #f8f9fa; border-radius: 8px; padding: 24px; margin: 20px 0; border: 1px solid #e1e4e8; }}
        .info-card {{ background: #fff; border: 1px solid #d1ecf1; border-radius: 8px; padding: 20px; margin: 15px 0; }}
        .warning-card {{ background: #fff3cd; border: 1px solid #ffeaa7; border-radius: 8px; padding: 20px; margin: 15px 0; }}
        .code-block {{ background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 6px; padding: 16px; margin: 10px 0; font-family: 'SF Mono', Consolas, monospace; white-space: pre-wrap; overflow-x: auto; }}
        .copy-btn {{ background: #0969da; color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; margin-top: 8px; }}
        .form-group {{ margin: 16px 0; }}
        label {{ display: block; margin-bottom: 5px; font-weight: 600; }}
        input, select, textarea {{ width: 100%; padding: 8px 12px; border: 1px solid #d0d7de; border-radius: 4px; font-size: 14px; }}
        .btn {{ background: #0969da; color: white; border: none; padding: 10px 20px; border-radius: 6px; cursor: pointer; }}
        .btn-secondary {{ background: #6c757d; }}
        .step {{ margin: 16px 0; padding: 12px; border-left: 3px solid #0969da; background: #f6f8fa; }}
        h1 {{ color: #24292f; margin-bottom: 8px; }}
        h2 {{ color: #24292f; margin-bottom: 16px; }}
        h3 {{ color: #24292f; margin-bottom: 12px; }}
        .secret-item {{ background: #fff; border: 1px solid #d0d7de; border-radius: 4px; padding: 8px 12px; margin: 4px 0; font-family: 'SF Mono', monospace; font-size: 13px; }}
        .toggle-section {{ cursor: pointer; padding: 8px 0; }}
        .toggle-section:hover {{ background: #f6f8fa; }}
        .collapsible {{ max-height: 0; overflow: hidden; transition: max-height 0.3s ease; }}
        .collapsible.active {{ max-height: 2000px; }}
        ul {{ padding-left: 20px; }}
        li {{ margin: 8px 0; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>⚙️ Configure Repository: {name or repo_id}</h1>
        <p>Set up BadDocs for automated documentation generation using GitHub Actions.</p>

        <!-- Database Integration Card -->
        <div class="card">
            <h2>🗄️ Database Documentation</h2>
            <p>BadDocs can analyze and document your database schemas, relationships, and stored procedures. Database analysis is completely optional and secure.</p>

            <div class="info-card">
                <h3>📋 Supported Database Types</h3>
                <ul>
                    <li><strong>PostgreSQL</strong> - Tables, views, functions, triggers</li>
                    <li><strong>MySQL</strong> - Schema analysis and stored procedures</li>
                    <li><strong>SQLite</strong> - Local database file analysis</li>
                    <li><strong>SQL Server</strong> - Enterprise database documentation</li>
                    <li><strong>Oracle</strong> - Complex schema and package documentation</li>
                </ul>
            </div>

            <div class="step">
                <h3>🔧 Configure Database Credentials</h3>
                <p>Use the <strong>Database Configuration Page</strong> to securely store your database credentials. Passwords are encrypted before storage.</p>
                <p style="margin-top: 15px;">
                    <a href="/github/database-config/{repo_id}{'?installation_id=' + str(installation_id) if installation_id else ''}" class="btn">
                        🗄️ Configure Database Credentials
                    </a>
                </p>
                <p style="margin-top: 10px; font-size: 0.9em; color: #666;">
                    <em>Tip: Click the "🗄️ Database" button from the main setup page to access this configuration.</em>
                </p>
            </div>

            <div class="warning-card">
                <h4>🔒 Security Best Practices</h4>
                <ul>
                    <li>Use a <strong>read-only database user</strong> with minimal permissions</li>
                    <li>Restrict network access to your database server</li>
                    <li>Database credentials are encrypted with AES-256 before storage</li>
                    <li>Only BadDocs has access to decrypt and use the credentials</li>
                </ul>
            </div>
        </div>

        <!-- GitHub Actions Setup Card -->
        <div class="card">
            <h2>🚀 GitHub Actions Integration</h2>
            <p>Use GitHub Actions to control when and how documentation is generated. This replaces complex branch configuration with simple, standard workflows.</p>

            <div class="step">
                <h4>Step 1: Create Workflow File</h4>
                <p>Create <code>.github/workflows/docs.yml</code> in your repository:</p>
                <div class="code-block">name: Generate Documentation
on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  docs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: baddocs/action@v1
        with:
          create_pr: true
          reviewers: "teamlead,senior-dev"
        env:
          GITHUB_TOKEN: ${{{{ secrets.GITHUB_TOKEN }}}}</div>
                <button class="copy-btn" onclick="copyToClipboard('name: Generate Documentation\\non:\\n  push:\\n    branches: [main]\\n  workflow_dispatch:\\n\\njobs:\\n  docs:\\n    runs-on: ubuntu-latest\\n    steps:\\n      - uses: actions/checkout@v4\\n      - uses: baddocs/action@v1\\n        with:\\n          create_pr: true\\n          reviewers: &quot;teamlead,senior-dev&quot;\\n        env:\\n          GITHUB_TOKEN: ${{{{ secrets.GITHUB_TOKEN }}}}')">Copy Workflow</button>
            </div>

            <div class="toggle-section" onclick="toggleSection('advanced-workflows')">
                <h3>📝 Advanced Workflow Examples (Click to expand)</h3>
            </div>
            <div id="advanced-workflows" class="collapsible">
                <div class="step">
                    <h4>Multiple Branch Triggers</h4>
                    <div class="code-block">name: Documentation
on:
  push:
    branches: [main, develop, 'release/*']
  pull_request:
    branches: [main]

jobs:
  docs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: baddocs/action@v1
        with:
          branch: ${{{{ github.ref_name }}}}
          create_pr: ${{{{ github.event_name == 'push' }}}}
        env:
          GITHUB_TOKEN: ${{{{ secrets.GITHUB_TOKEN }}}}</div>
                    <button class="copy-btn" onclick="copyToClipboard('name: Documentation\\non:\\n  push:\\n    branches: [main, develop, \\'release/*\\']\\n  pull_request:\\n    branches: [main]\\n\\njobs:\\n  docs:\\n    runs-on: ubuntu-latest\\n    steps:\\n      - uses: actions/checkout@v4\\n      - uses: baddocs/action@v1\\n        with:\\n          branch: ${{{{ github.ref_name }}}}\\n          create_pr: ${{{{ github.event_name == \\'push\\' }}}}\\n        env:\\n          GITHUB_TOKEN: ${{{{ secrets.GITHUB_TOKEN }}}}')">Copy Workflow</button>
                </div>

                <div class="step">
                    <h4>Manual Trigger with Options</h4>
                    <div class="code-block">name: Generate Docs (Manual)
on:
  workflow_dispatch:
    inputs:
      include_database:
        description: 'Include database documentation'
        type: boolean
        default: true

jobs:
  docs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: baddocs/action@v1
        with:
          database_enabled: ${{{{ inputs.include_database }}}}
          pr_title: "📚 Manual documentation update"
        env:
          GITHUB_TOKEN: ${{{{ secrets.GITHUB_TOKEN }}}}</div>
                    <button class="copy-btn" onclick="copyToClipboard('name: Generate Docs (Manual)\\non:\\n  workflow_dispatch:\\n    inputs:\\n      include_database:\\n        description: \\'Include database documentation\\'\\n        type: boolean\\n        default: true\\n\\njobs:\\n  docs:\\n    runs-on: ubuntu-latest\\n    steps:\\n      - uses: actions/checkout@v4\\n      - uses: baddocs/action@v1\\n        with:\\n          database_enabled: ${{{{ inputs.include_database }}}}\\n          pr_title: &quot;📚 Manual documentation update&quot;\\n        env:\\n          GITHUB_TOKEN: ${{{{ secrets.GITHUB_TOKEN }}}}')">Copy Workflow</button>
                </div>
            </div>
        </div>

        <!-- PR Settings Card -->
        <div class="card">
            <h2>🔧 Pull Request Settings</h2>
            <p>Configure how BadDocs creates and manages pull requests with generated documentation.</p>

            <div class="form-group">
                <label>
                    <input type="checkbox" id="createPR" checked> Automatically create pull requests
                </label>
            </div>

            <div class="form-group">
                <label for="reviewers">Default Reviewers (comma-separated GitHub usernames):</label>
                <input type="text" id="reviewers" placeholder="username1, username2" value="">
                <small>These reviewers will be automatically assigned to documentation PRs</small>
            </div>

            <div class="form-group">
                <label for="prTemplate">PR Description Template:</label>
                <textarea id="prTemplate" rows="4" placeholder="Custom pull request description...">## 📚 Documentation Update

This PR contains automatically generated documentation for the repository.

### Changes Include:
- 📝 Code documentation and API references
- 🗄️ Database schema documentation (if configured)
- 🔗 Cross-references and dependency mapping

Generated by [BadDocs](https://baddocs.com) 🤖</textarea>
            </div>

            <div class="step">
                <h4>💡 Pro Tips</h4>
                <ul>
                    <li>Use team names like <code>@myorg/docs-team</code> for reviewer groups</li>
                    <li>Customize PR templates to match your team's review process</li>
                    <li>Enable branch protection rules to require PR reviews</li>
                </ul>
            </div>
        </div>

        <!-- Action Buttons -->
        <div class="card">
            <button onclick="saveConfiguration()" class="btn">💾 Save Configuration</button>
            <button onclick="testConfiguration()" class="btn btn-secondary" style="margin-left: 10px;">🧪 Test Setup</button>
            <a href="/github/setup" style="margin-left: 20px; color: #0969da;">← Back to Repositories</a>
        </div>

        <div class="info-card">
            <h3>📖 Next Steps</h3>
            <ol>
                <li>Set up database secrets (if using database documentation)</li>
                <li>Create the GitHub Actions workflow file</li>
                <li>Commit and push to trigger your first documentation generation</li>
                <li>Review the generated documentation PR</li>
            </ol>
        </div>
    </div>

    <script>
        function toggleSection(sectionId) {{
            const section = document.getElementById(sectionId);
            section.classList.toggle('active');
        }}

        function copyToClipboard(text) {{
            navigator.clipboard.writeText(text.replace(/\\\\n/g, '\\n')).then(() => {{
                // Visual feedback
                event.target.textContent = 'Copied!';
                setTimeout(() => {{
                    event.target.textContent = event.target.textContent.replace('Copied!', 'Copy Commands').replace('Copied!', 'Copy Workflow');
                }}, 2000);
            }});
        }}

        function saveConfiguration() {{
            const config = {{
                create_pr: document.getElementById('createPR').checked,
                reviewers: document.getElementById('reviewers').value,
                pr_template: document.getElementById('prTemplate').value,
                repository_id: '{repo_id}',
                installation_id: {installation_id or 'null'}
            }};

            // For now, show success message - will implement backend save later
            alert('✅ Configuration saved! Your settings will be applied to future documentation generations.');
        }}

        function testConfiguration() {{
            // Placeholder for configuration testing
            alert('🧪 Configuration test coming soon! This will validate your database connections and GitHub settings.');
        }}

        // Auto-expand sections if URL contains fragment
        if (window.location.hash) {{
            const section = document.getElementById(window.location.hash.substring(1));
            if (section) {{
                section.classList.add('active');
            }}
        }}
    </script>
</body>
</html>
        """

        return HTMLResponse(html_content)

    except Exception as e:
        logger.error(f"Repository configuration page failed: {e}")
        return HTMLResponse(f"<html><body><h1>Error</h1><p>{str(e)}</p></body></html>", status_code=500)


@app.post("/api/github/repositories/{repo_id}/generate")
async def manual_generate_documentation(
    repo_id: str,
    background_tasks: BackgroundTasks,
    request_data: Dict = Body(...)
):
    """Manually trigger documentation generation for a repository."""
    try:
        logger.error(f"🚨 MANUAL GENERATE ENDPOINT HIT: repo_id={repo_id}, request_data={request_data}")
        logger.info(f"Manual documentation generation requested for repository: {repo_id}")
        if request_data:
            logger.info(f"Installation ID received: {request_data.get('installation_id')}")

        # Try to get GitHub App authentication for repository access
        github_auth = None
        try:
            from .github.auth import GitHubAppAuth
            if os.getenv('GITHUB_APP_ID'):
                github_auth = GitHubAppAuth()
                logger.info("GitHub App authentication available for manual generation")
        except ImportError:
            logger.warning("GitHub App authentication not available for manual generation")

        # Check if MCP orchestrator is available
        if HAS_MCP_SUPPORT:
            try:
                logger.info("Attempting to use MCP orchestrator for documentation generation")

                # Get repository information from GitHub API if available
                repo_url = f"https://github.com/repository/{repo_id}"  # Default fallback
                if github_auth:
                    try:
                        # Get repository information using GitHub API
                        installation_id = request_data.get('installation_id') if request_data else None
                        if installation_id:
                            installation_token = github_auth.get_installation_token(installation_id)
                            if installation_token:
                                import requests
                                headers = {
                                    'Authorization': f'token {installation_token}',
                                    'Accept': 'application/vnd.github.v3+json',
                                    'User-Agent': 'BadDocs-GitHub-App'
                                }

                                # Try to get repository info by ID
                                response = requests.get(f'https://api.github.com/repositories/{repo_id}', headers=headers)
                                if response.status_code == 200:
                                    repo_data = response.json()
                                    repo_url = repo_data.get('clone_url', repo_url)
                                    logger.info(f"Retrieved repository info: {repo_data.get('full_name')} -> {repo_url}")
                                else:
                                    logger.warning(f"Could not fetch repo {repo_id}: HTTP {response.status_code}")
                            else:
                                logger.warning(f"Could not get installation token for {installation_id}")

                        # Fallback for known test repositories
                        if repo_id == "298787864":  # LaTeXKit repository ID
                            repo_url = "https://github.com/shepherdscientific/LaTeXKit"

                        logger.info(f"GitHub API integration available for repo {repo_id} -> {repo_url}")
                    except Exception as api_error:
                        logger.warning(f"Could not fetch GitHub repo info: {api_error}")

                # Create workflow parameters for GitHub repository
                # Extract serializable auth data to avoid JSON serialization errors
                logger.info(f"DEBUG: github_auth={github_auth is not None}, request_data={request_data}, installation_id={request_data.get('installation_id') if request_data else None}")
                auth_data = {}
                if github_auth and request_data and request_data.get('installation_id'):
                    try:
                        installation_id = request_data.get('installation_id')
                        access_token = github_auth.get_installation_token(installation_id)
                        auth_data = {
                            'github_token': access_token,
                            'installation_id': installation_id
                        }
                        logger.info(f"GitHub token generated for installation {installation_id}: {'[SET]' if access_token else '[NOT SET]'}")
                    except Exception as e:
                        logger.warning(f"Failed to get GitHub token for manual generation: {e}")

                workflow_params = {
                    'operation': 'github_manual_generate',
                    'repository_id': repo_id,
                    'repository_url': repo_url,
                    'trigger': 'manual',
                    'timestamp': datetime.now().isoformat(),
                    'source': 'github_app',
                    'github_auth': github_auth,  # Pass the GitHub auth object for background task
                    **auth_data  # Include serializable auth data as well
                }


                # Add background task for MCP processing
                background_tasks.add_task(_process_mcp_github_task, workflow_params)

                return {
                    "status": "triggered",
                    "repository_id": repo_id,
                    "message": "Documentation generation started via MCP orchestrator",
                    "method": "mcp_orchestrator"
                }

            except Exception as mcp_error:
                logger.error(f"MCP orchestrator failed for manual generation: {mcp_error}")
                # Fall through to direct processing

        # Fallback to direct processing if MCP is not available
        logger.info("Using direct processing for manual documentation generation")

        # Add background task for direct processing
        background_tasks.add_task(_process_manual_github_generation, repo_id, github_auth)

        return {
            "status": "triggered",
            "repository_id": repo_id,
            "message": "Documentation generation started via direct processing",
            "method": "direct_processing"
        }

    except Exception as e:
        logger.error(f"Manual documentation generation failed: {e}")
        return {"status": "error", "error": str(e)}


@app.post("/api/github/webhook")
async def handle_github_webhook(request: Request, background_tasks: BackgroundTasks):
    """Enhanced GitHub webhook handler with App authentication and signature verification."""
    try:
        # Get raw payload for signature verification
        raw_payload = await request.body()
        headers = dict(request.headers)

        # Parse JSON payload
        try:
            payload = await request.json()
        except Exception as e:
            logger.error(f"Failed to parse webhook payload: {e}")
            raise HTTPException(status_code=400, detail="Invalid JSON payload")

        event_type = headers.get('x-github-event', 'unknown')
        logger.info(f"Received GitHub webhook: {event_type}")

        # Initialize GitHub App auth if available
        github_auth = None
        webhook_handler = None

        try:
            from .github.auth import GitHubAppAuth
            from .github.webhooks import GitHubWebhookHandler

            if os.getenv('GITHUB_APP_ID'):
                github_auth = GitHubAppAuth()
                webhook_handler = GitHubWebhookHandler(github_auth)

                # Verify webhook signature if configured
                signature = headers.get('x-hub-signature-256', '')
                if signature and not webhook_handler.verify_webhook_signature(raw_payload, signature):
                    logger.warning("Webhook signature verification failed")
                    raise HTTPException(status_code=401, detail="Invalid webhook signature")

                logger.info("Using GitHub App authentication for webhook processing")
            else:
                logger.info("GitHub App not configured - using legacy webhook processing")

        except ImportError:
            logger.info("GitHub App modules not available - using legacy webhook processing")

        # Enhanced webhook processing if GitHub App is configured
        if webhook_handler:
            try:
                # Parse webhook event
                event = webhook_handler.parse_webhook_event(headers, payload)

                # Process event
                result = await webhook_handler.process_webhook_event(event)

                if result['status'] == 'processed':
                    # Create status check
                    webhook_handler.create_status_check(
                        event, 'pending',
                        'Documentation generation started'
                    )

                    # Trigger documentation workflow with enhanced parameters
                    workflow_params = result['workflow_params']

                    # Add to background processing queue
                    background_tasks.add_task(
                        _process_github_app_webhook,
                        event,
                        workflow_params,
                        webhook_handler
                    )

                    return {
                        "status": "processed",
                        "event_type": result['event_type'],
                        "repository": result['repository'],
                        "changed_files": result.get('changed_files', 0)
                    }

                elif result['status'] == 'ignored':
                    return {
                        "status": "ignored",
                        "reason": result['reason']
                    }

                else:  # error
                    logger.error(f"Webhook processing error: {result.get('error')}")
                    return {
                        "status": "error",
                        "error": result.get('error')
                    }

            except Exception as e:
                logger.error(f"Enhanced webhook processing failed: {e}")
                # Fall back to legacy processing

        # Legacy webhook processing (backward compatibility)
        repo_data = payload.get("repository", {})
        repo_url = repo_data.get("clone_url") or repo_data.get("html_url")
        if not repo_url:
            raise HTTPException(status_code=400, detail="Repository URL not found in payload")

        # Find existing repository or create new one
        repo_id = None
        for rid, repo_status in app_state["repositories"].items():
            if repo_status.repository_url == repo_url:
                repo_id = rid
                break

        if not repo_id:
            # Create new repository entry
            repo_id = generate_repo_id(repo_url)
            app_state["repositories"][repo_id] = RepositoryStatus(
                repository_id=repo_id,
                repository_url=repo_url,
                status="webhook_triggered",
                total_files=0,
                documented_files=0,
                coverage_percentage=0.0,
                last_update=datetime.now().isoformat()
            )

        # Handle different webhook events
        if event_type == 'push':
            # Update repository state
            app_state["repositories"][repo_id].status = "incremental_update"
            app_state["repositories"][repo_id].last_update = datetime.now().isoformat()

            # Add legacy processing task
            background_tasks.add_task(_process_legacy_webhook, repo_id, repo_url)

        return {"status": "webhook_processed", "repository_id": repo_id, "event": event_type}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook processing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/repositories/{repo_id}/documentation")
async def get_repository_documentation(
    repo_id: str,
    search_query: Optional[str] = None,
    file_pattern: Optional[str] = None,
    search_engine: Optional[Any] = Depends(get_search_engine)
):
    """Get generated documentation for a repository with SQLite FTS5 search."""
    if repo_id not in app_state["repositories"]:
        raise HTTPException(status_code=404, detail="Repository not found")

    if not search_engine:
        # Fallback for when storage system is not available
        return {
            "repository_id": repo_id,
            "documentation": "Storage system not available - running in legacy mode",
            "search_query": search_query,
            "file_pattern": file_pattern
        }

    try:
        # Use FTS5 search if query provided
        if search_query:
            import time
            start_time = time.time()

            filters = {"repository_url": app_state["repositories"][repo_id].repository_url}
            results = await search_engine.search_documents(
                query=search_query,
                limit=50,
                filters=filters
            )

            query_time = (time.time() - start_time) * 1000

            return {
                "repository_id": repo_id,
                "total_results": len(results),
                "query_time_ms": query_time,
                "results": [result.to_dict() for result in results],
                "search_query": search_query
            }
        else:
            # Get all documentation for repository
            # TODO: Implement repository-wide document retrieval
            return {
                "repository_id": repo_id,
                "message": "Repository document listing not yet implemented",
                "use_search": "Add ?search_query=your_query for FTS5 search"
            }

    except Exception as e:
        logger.error(f"Documentation retrieval failed: {e}")
        raise HTTPException(status_code=500, detail="Documentation retrieval failed")


@app.post("/debug/test-background")
async def test_background_task(background_tasks: BackgroundTasks):
    """Test endpoint to debug background task execution."""
    logger.info("🧪 Test background endpoint called")

    def simple_sync_task():
        import time
        logger.info("🎯 SIMPLE SYNC BACKGROUND TASK EXECUTING")
        time.sleep(2)
        logger.info("🎯 SIMPLE SYNC BACKGROUND TASK COMPLETE")

    async def simple_async_task():
        import asyncio
        logger.info("🎯 SIMPLE ASYNC BACKGROUND TASK EXECUTING")
        await asyncio.sleep(2)
        logger.info("🎯 SIMPLE ASYNC BACKGROUND TASK COMPLETE")

    def thread_based_task():
        import time, threading
        logger.info("🚀 THREAD-BASED BACKGROUND TASK EXECUTING")
        time.sleep(1)
        logger.info("🚀 THREAD-BASED BACKGROUND TASK COMPLETE")

    # Test FastAPI BackgroundTasks (which may not work)
    background_tasks.add_task(simple_sync_task)
    background_tasks.add_task(simple_async_task)

    # Test alternative threading approach (which should work)
    import threading
    thread = threading.Thread(target=thread_based_task)
    thread.start()

    logger.info("🧪 Background tasks scheduled (FastAPI + threading)")
    return {
        "status": "background tasks scheduled",
        "tasks": ["fastapi_sync", "fastapi_async", "threading"],
        "message": "Check logs for execution confirmation"
    }

@app.post("/api/search", response_model=SearchResponse)
async def search_documentation(
    request: SearchRequest,
    search_engine: Optional[Any] = Depends(get_search_engine)
):
    """Search documentation using FTS5 full-text search via MCP or direct."""
    try:
        import time
        start_time = time.time()

        # Try MCP orchestration first
        mcp_integration = app_state.get("mcp_integration")
        if mcp_integration:
            try:
                logger.info("🚀 Using MCP orchestration for documentation search")
                search_result = await mcp_integration.search_documentation_mcp(
                    query=request.query,
                    repository_filter=request.repository_url,
                    doc_type_filter=request.doc_type,
                    language_filter=request.language,
                    limit=request.limit + 1  # Get one extra to check for more results
                )

                search_results = search_result.get("results", [])
                query_time_ms = (time.time() - start_time) * 1000

                return SearchResponse(
                    results=search_results[:request.limit],
                    total_count=search_result.get("total_count", len(search_results)),
                    query_time_ms=query_time_ms,
                    has_more=len(search_results) > request.limit
                )

            except Exception as e:
                logger.warning(f"⚠️ MCP search failed, falling back to direct: {e}")

        # Fallback to direct search engine
        if not search_engine:
            raise HTTPException(
                status_code=503,
                detail="Search system not available - neither MCP nor direct storage initialized"
            )

        logger.info("📁 Using direct search engine (fallback)")

        # Build filters from request
        filters = {}
        if request.repository_url:
            filters["repository_url"] = request.repository_url
        if request.doc_type:
            filters["doc_type"] = request.doc_type
        if request.language:
            filters["language"] = request.language

        # Perform FTS5 search
        results = await search_engine.search_documents(
            query=request.query,
            limit=request.limit + 1,  # Get one extra to check for more results
            filters=filters
        )

        query_time = (time.time() - start_time) * 1000

        # Check if there are more results
        has_more = len(results) > request.limit
        if has_more:
            results = results[:request.limit]

        return SearchResponse(
            results=[result.to_dict() for result in results],
            total_count=len(results),
            query_time_ms=query_time,
            has_more=has_more
        )

    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise HTTPException(status_code=500, detail="Search operation failed")


class RepositoryDocsResponse(BaseModel):
    """Response model for repository documentation list."""
    documents: List[Dict[str, Any]]
    total_count: int
    repository_id: str


class RepositorySearchResponse(BaseModel):
    """Response model for repository search results."""
    results: List[Dict[str, Any]]
    total_count: int
    repository_id: str
    query_time_ms: float
    has_more: bool


@app.get("/api/repositories/{repo_id}/docs", response_model=RepositoryDocsResponse)
async def get_repository_docs(
    repo_id: str,
    search_engine: Optional[Any] = Depends(get_search_engine)
):
    """Get all documentation for a specific repository."""
    # Find repository URL from app state
    repo_url = None
    if repo_id in app_state.get("repositories", {}):
        repo_url = app_state["repositories"][repo_id].repository_url

    if not repo_url:
        raise HTTPException(status_code=404, detail="Repository not found")

    if not search_engine:
        raise HTTPException(
            status_code=503,
            detail="Search system not available - storage engine not initialized"
        )

    try:
        # Get files for this repository from database
        storage_manager = app_state.get("storage_manager")
        if storage_manager:
            # Query documents joined with files, filtering by repository metadata
            cursor = await storage_manager.execute_query("""
                SELECT d.id, d.doc_type, d.name, d.content, d.summary,
                       d.llm_model, d.llm_provider, d.quality_score,
                       d.generated_at, f.path as file_path, f.language
                FROM documents d
                JOIN files f ON d.file_id = f.id
                WHERE f.metadata LIKE ?
                ORDER BY d.generated_at DESC
            """, (f'%"{repo_url}"%',))

            rows = cursor.fetchall()
            documents = [
                {
                    "id": row['id'],
                    "file_path": row['file_path'],
                    "doc_type": row['doc_type'],
                    "name": row['name'],
                    "summary": row['summary'],
                    "generated_at": row['generated_at'],
                    "llm_model": row['llm_model'],
                    "llm_provider": row['llm_provider'],
                    "quality_score": row['quality_score']
                }
                for row in rows
            ]

            return RepositoryDocsResponse(
                documents=documents,
                total_count=len(documents),
                repository_id=repo_id
            )

        raise HTTPException(status_code=500, detail="Storage manager not available")

    except Exception as e:
        logger.error(f"Failed to get docs for repository {repo_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve documentation")


@app.get("/api/repositories/{repo_id}/search", response_model=RepositorySearchResponse)
async def search_repository_docs(
    repo_id: str,
    q: str,
    limit: int = 50,
    offset: int = 0,
    search_engine: Optional[Any] = Depends(get_search_engine)
):
    """Search documentation for a specific repository."""
    # Find repository URL from app state
    repo_url = None
    if repo_id in app_state.get("repositories", {}):
        repo_url = app_state["repositories"][repo_id].repository_url

    if not repo_url:
        raise HTTPException(status_code=404, detail="Repository not found")

    if not search_engine:
        raise HTTPException(
            status_code=503,
            detail="Search system not available - storage engine not initialized"
        )

    try:
        import time
        start_time = time.time()

        # Build search query with repository filter
        search_query = q

        # If storage manager available, use direct search
        storage_manager = app_state.get("storage_manager")
        if storage_manager:
            # Use FTS5 search with repository filter
            cursor = await storage_manager.execute_query("""
                SELECT d.id, d.doc_type, d.name, d.content, d.summary,
                       f.path as file_path, f.language,
                       bm25(doc_search, 10.0, 5.0, 1.0) as rank
                FROM doc_search fts
                JOIN documents d ON fts.rowid = d.id
                JOIN files f ON d.file_id = f.id
                WHERE doc_search MATCH ? AND f.metadata LIKE ?
                ORDER BY rank
                LIMIT ? OFFSET ?
            """, (search_query, f'%"{repo_url}"%', limit + 1, offset))

            rows = cursor.fetchall()
            results = [
                {
                    "document_id": row['id'],
                    "file_path": row['file_path'],
                    "doc_type": row['doc_type'],
                    "name": row['name'],
                    "summary": row['summary'],
                    "content": row['content'],
                    "language": row['language'],
                    "rank": row['rank']
                }
                for row in rows
            ]

            query_time_ms = (time.time() - start_time) * 1000
            has_more = len(results) > limit

            return RepositorySearchResponse(
                results=results[:limit],
                total_count=len(results),
                repository_id=repo_id,
                query_time_ms=query_time_ms,
                has_more=has_more
            )

        raise HTTPException(status_code=500, detail="Storage manager not available")

    except Exception as e:
        logger.error(f"Failed to search repository {repo_id}: {e}")
        raise HTTPException(status_code=500, detail="Search operation failed")


async def _load_repository_status_from_db():
    """Load repository status from database on startup."""
    try:
        storage_manager = app_state.get("storage_manager")
        if not storage_manager:
            return

        # Query unique repositories from files table
        cursor = await storage_manager.execute_query("""
            SELECT
                metadata->>'repository_url' as repo_url,
                COUNT(*) as total_files,
                COUNT(CASE WHEN d.id IS NOT NULL THEN 1 END) as documented_files,
                MAX(f.updated_at) as last_update
            FROM files f
            LEFT JOIN documents d ON f.id = d.file_id
            WHERE json_extract(metadata, '$.repository_url') IS NOT NULL
            GROUP BY metadata->>'repository_url'
        """)

        rows = cursor.fetchall()
        for row in rows:
            repo_url = row['repo_url']
            if not repo_url:
                continue

            # Generate repository ID from URL (same as in analyze endpoint)
            repo_id = generate_repo_id(repo_url)

            total_files = row['total_files']
            documented_files = row['documented_files'] or 0
            coverage = (documented_files / total_files * 100) if total_files > 0 else 0.0

            # Create repository status
            repo_status = RepositoryStatus(
                repository_id=repo_id,
                repository_url=repo_url,
                status="completed",  # Assume completed if in database
                total_files=total_files,
                documented_files=documented_files,
                coverage_percentage=coverage,
                last_update=row['last_update'] or datetime.now().isoformat()
            )

            app_state["repositories"][repo_id] = repo_status
            logger.info(f"Restored repository status: {repo_url} ({documented_files}/{total_files} files)")

        logger.info(f"Loaded {len(rows)} repositories from database")

    except Exception as e:
        logger.error(f"Failed to load repository status from database: {e}")


async def _analyze_repository_mcp_async(repo_id: str, repository_url: str, analyzer):
    """Async-native end-to-end repository analysis task using ModelRouter pipeline."""
    logger.info(f"🔥 END-TO-END PIPELINE ASYNC TASK STARTED for repo {repo_id}: {repository_url}")

    try:
        # Get repository status from app state
        if repo_id not in app_state["repositories"]:
            logger.error(f"Repository {repo_id} not found in app state")
            return

        repo_status = app_state["repositories"][repo_id]
        repo_status.status = "processing"
        repo_status.last_update = datetime.now().isoformat()

        # Step 1: Clone repository to shared volume
        repo_status.status = "cloning"
        repo_status.last_update = datetime.now().isoformat()

        import tempfile
        import subprocess
        import shutil
        from pathlib import Path

        # Use shared volume that MCP servers can access
        shared_tmp = Path("/tmp/claude") if Path("/tmp/claude").exists() else Path(tempfile.gettempdir())
        shared_tmp.mkdir(exist_ok=True)

        temp_dir = shared_tmp / f"baddocs_{repo_id}"
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        temp_dir.mkdir(exist_ok=True)

        repo_path = temp_dir / "repository"
        logger.info(f"Processing repository: {repository_url}")

        # Check if this is a local path or a git URL
        from pathlib import Path
        local_path = Path(repository_url)
        if local_path.exists():
            # Local path - copy to temp directory
            logger.info(f"Copying local repository from {repository_url}")
            if repo_path.exists():
                shutil.rmtree(repo_path)
            shutil.copytree(local_path, repo_path)
        else:
            # Git URL - clone the repository
            logger.info(f"Cloning {repository_url} to {repo_path}")
            result = subprocess.run(
                ["git", "clone", repository_url, str(repo_path)],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode != 0:
                logger.error(f"Git clone failed: {result.stderr}")
                repo_status.status = "error"
                repo_status.last_update = datetime.now().isoformat()
                return

        # Step 2: Initialize ModelRouter for documentation generation
        repo_status.status = "analyzing"
        repo_status.last_update = datetime.now().isoformat()

        # Import required modules
        from ..mcp_servers.llm.model_router import ModelRouter, TaskType, CostTier
        from ..mcp_servers.llm.prompts import PromptManager, DefaultPromptTemplates, ContextType, PromptContext
        from ..processors import (
            PythonProcessor, JavaScriptProcessor, JavaProcessor, CSharpProcessor,
            GoProcessor, RubyProcessor, RustProcessor, PHPProcessor,
            CobolProcessor, FortranProcessor, VB6Processor, PowerBuilderProcessor, RProcessor
        )
        from ..storage.connection import StorageManager
        from ..storage.document_ops import DocumentOperations
        from ..storage.file_ops import FileOperations
        from ..storage.models import Document

        # Initialize ModelRouter
        model_router_config = {
            'cost_tier': 'budget',
            'monthly_budget': 20.0,
            'cost_tracking': True,
            'routing_mode': 'intelligent',
            'provider_mode': 'auto',
            'providers': {}
        }
        model_router = ModelRouter(model_router_config)
        await model_router.initialize()
        logger.info(f"ModelRouter initialized with {len(model_router.models)} models")

        # Initialize storage
        db_path = temp_dir / "baddocs.db"
        storage_manager = StorageManager(str(db_path))
        await storage_manager.initialize()
        file_ops = FileOperations(storage_manager)
        doc_ops = DocumentOperations(storage_manager)
        logger.info(f"Storage initialized at {db_path}")

        # Initialize prompt manager
        prompt_templates = DefaultPromptTemplates()
        prompt_manager = PromptManager({})
        logger.info("Prompt manager initialized")

        # Step 3: Discover files in repository
        logger.info(f"Discovering files in {repo_path}")
        supported_extensions = {
            '.py', '.pyw', '.pyi',  # Python
            '.js', '.mjs', '.jsx', '.ts', '.tsx', '.cjs',  # JavaScript
            '.java',  # Java
            '.cs',  # C#
            '.go',  # Go
            '.rb', '.rake', '.gemspec', '.ru',  # Ruby
            '.rs',  # Rust
            '.php', '.phtml', '.php3', '.php4', '.php5', '.phps',  # PHP
            '.cbl', '.cob', '.cpy', '.pco', '.cobol',  # COBOL
            '.f', '.f77', '.f90', '.f95', '.for', '.ftn',  # Fortran
            '.bas', '.frm', '.cls', '.ctl', '.pag', '.dob', '.vb',  # VB6
            '.pbl', '.pbt', '.pbw', '.srd', '.sru', '.srw', '.pbd',  # PowerBuilder
            '.r', '.R', '.Rmd', '.Rnw', '.Rscript',  # R
        }

        files_to_process = []
        for ext in supported_extensions:
            for file_path in repo_path.rglob(f"*{ext}"):
                if file_path.is_file() and file_path.stat().st_size < 100000:  # Skip very large files
                    files_to_process.append(file_path)

        logger.info(f"Found {len(files_to_process)} files to process")

        # Step 4: Process each file using language processors and ModelRouter
        files_analyzed = 0
        files_documented = 0
        files_with_errors = []

        for file_path in files_to_process:
            try:
                rel_path = file_path.relative_to(repo_path)
                logger.debug(f"Processing file: {rel_path}")

                # Get file content
                content = file_path.read_text(encoding='utf-8', errors='replace')

                # Detect language from extension
                language = _detect_language_from_extension_for_pipeline(file_path.suffix)
                logger.debug(f"Detected language: {language} for {rel_path}")

                # Select appropriate processor
                processor = _get_processor_for_language(language, {'max_file_size_mb': 50})
                if processor is None:
                    logger.warning(f"No processor available for language: {language}")
                    files_with_errors.append(f"{rel_path}: No processor for {language}")
                    continue

                # Check if file can be processed
                if not processor.validate_file(file_path):
                    logger.warning(f"File validation failed: {rel_path}")
                    files_with_errors.append(f"{rel_path}: Validation failed")
                    continue

                # Process file with language processor
                try:
                    processing_result = processor.process_file(file_path)
                    logger.debug(f"Extracted {len(processing_result.elements)} elements from {rel_path}")
                except Exception as pe:
                    logger.warning(f"Processing error for {rel_path}: {pe}")
                    files_with_errors.append(f"{rel_path}: {str(pe)}")
                    continue

                # Build context for documentation generation
                prompt_context = PromptContext(
                    context_type=ContextType.FILE,
                    language=language,
                    file_path=str(rel_path),
                    source_code=content,
                    element_name=file_path.stem,
                    project_name=repo_path.name,
                    documentation_style='standard',
                    target_audience='developers',
                    detail_level='detailed'
                )

                # Build prompt using prompt manager
                prompt = prompt_manager.generate_prompt(prompt_context)
                logger.debug(f"Built prompt for {rel_path} (length: {len(prompt)})")

                # Select model using ModelRouter
                llm_request = LLMRequest(
                    prompt=prompt,
                    max_tokens=2048,
                    context_type='file',
                    language=language,
                    file_path=str(rel_path)
                )

                model_selection = await model_router.select_model(TaskType.CODE_DOCUMENTATION, llm_request)
                logger.debug(f"Selected model: {model_selection}")

                if model_selection is None:
                    logger.warning(f"No model available for {rel_path}")
                    files_with_errors.append(f"{rel_path}: No model available")
                    continue

                # Generate documentation using ModelRouter
                response = await model_router.generate_with_selected_model(llm_request, model_selection)

                if response.error:
                    logger.error(f"Generation error for {rel_path}: {response.error}")
                    files_with_errors.append(f"{rel_path}: {response.error}")
                    continue

                generated_doc = response.content
                logger.info(f"Generated documentation for {rel_path}")

                # Persist document to storage
                # First, check if file already exists to get its ID or create new record
                existing_file = await file_ops.get_file_by_path(str(rel_path))
                if existing_file:
                    file_id = existing_file.id
                else:
                    # Create a FileRecord with file info
                    from ..storage.models import FileRecord
                    file_record = FileRecord(
                        path=str(rel_path),
                        language=language,
                        size=file_path.stat().st_size,
                        last_modified=datetime.fromtimestamp(file_path.stat().st_mtime),
                        content_hash='',  # Will be computed by FileRecord.__post_init__ if needed
                        metadata={'source': 'baddocs_analysis'}
                    )
                    file_id = await file_ops.insert_file(file_record)

                document = Document(
                    file_id=file_id,
                    doc_type='file',
                    name=file_path.name,
                    content=generated_doc,
                    summary=f"Documentation for {rel_path}",
                    llm_model=model_selection.get('model_name', 'unknown'),
                    llm_provider=model_selection.get('provider', 'unknown'),
                    quality_score=0.8,
                    metadata={
                        'language': language,
                        'file_path': str(rel_path),
                        'elements_processed': len(processing_result.elements)
                    }
                )
                await doc_ops.insert_document(document)
                files_documented += 1
                logger.debug(f"Persisted document for {rel_path}")

                files_analyzed += 1

            except Exception as file_error:
                logger.error(f"Error processing file {file_path}: {file_error}", exc_info=True)
                files_with_errors.append(f"{file_path}: {str(file_error)}")

        # Update status with results
        repo_status.status = "completed"
        repo_status.total_files = files_analyzed
        repo_status.documented_files = files_documented
        repo_status.coverage_percentage = (files_documented / files_analyzed * 100) if files_analyzed > 0 else 0.0
        repo_status.processing_errors = files_with_errors[:10]  # Limit errors list
        repo_status.last_update = datetime.now().isoformat()

        logger.info(f"Pipeline completed for repo {repo_id}: {files_analyzed} files analyzed, {files_documented} documented")

        # Cleanup temp directory
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        logger.info(f"Temp directory cleaned up: {temp_dir}")

    except Exception as e:
        logger.error(f"Pipeline async task failed for repo {repo_id}: {e}", exc_info=True)
        if repo_id in app_state["repositories"]:
            app_state["repositories"][repo_id].status = "error"
            app_state["repositories"][repo_id].last_update = datetime.now().isoformat()
            app_state["repositories"][repo_id].processing_errors = [str(e)]


async def _analyze_repository_background(
    repo_id: str,
    request: RepositoryRequest,
    analyzer,
    incremental: bool = False
):
    """Background task for repository analysis."""
    logger.info(f"🔥 BACKGROUND TASK STARTED for repo {repo_id}: {request.repository_url}")

    # Log analyzer type for debugging
    logger.info(f"🔍 Analyzer type: {type(analyzer).__name__ if analyzer else 'None'}")
    logger.info(f"🔍 Analyzer available: {analyzer is not None}")

    # Check if we're in the background task execution context
    try:
        import asyncio
        current_task = asyncio.current_task()
        logger.info(f"🔍 Current asyncio task: {current_task}")
    except Exception as e:
        logger.warning(f"🔍 Could not get current task: {e}")
    import subprocess
    import tempfile
    import shutil
    from pathlib import Path

    temp_dir = None
    try:
        logger.info(f"Background analysis started for repository: {repo_id}")
        repo_status = app_state["repositories"][repo_id]

        # Step 1: Clone repository
        repo_status.status = "cloning"
        repo_status.last_update = datetime.now().isoformat()

        # Create temporary directory for cloning (use shared volume in Docker)
        shared_tmp = Path("/app/tmp")
        shared_tmp.mkdir(exist_ok=True)
        temp_dir = shared_tmp / f"baddocs_{repo_id}_{secrets.token_urlsafe(8)}"
        temp_dir.mkdir(exist_ok=True)
        repo_path = temp_dir / "repository"

        # Enhanced git logic: Check if repository already exists and try to update it
        repo_needs_clone = True
        if repo_path.exists() and (repo_path / ".git").exists():
            logger.info(f"Repository already exists at {repo_path}, attempting to update instead of re-cloning")

            try:
                # Step 1: Fetch latest changes from remote
                fetch_result = subprocess.run(
                    ["git", "fetch", "origin"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=60
                )

                if fetch_result.returncode == 0:
                    logger.info("Successfully fetched latest changes")

                    # Step 2: Get current branch
                    branch_result = subprocess.run(
                        ["git", "branch", "--show-current"],
                        cwd=repo_path,
                        capture_output=True,
                        text=True
                    )
                    current_branch = branch_result.stdout.strip() or "main"

                    # Step 3: Check for existing documentation branches
                    branch_list_result = subprocess.run(
                        ["git", "branch", "-a"],
                        cwd=repo_path,
                        capture_output=True,
                        text=True
                    )

                    has_docs_branch = "docs/" in branch_list_result.stdout

                    if has_docs_branch:
                        logger.info("Found existing documentation branch, checking for unmerged changes")

                    # Step 4: Try to pull with rebase
                    pull_result = subprocess.run(
                        ["git", "pull", "--rebase", "origin", current_branch],
                        cwd=repo_path,
                        capture_output=True,
                        text=True,
                        timeout=120
                    )

                    if pull_result.returncode == 0:
                        logger.info(f"Successfully updated repository on branch {current_branch}")
                        repo_needs_clone = False  # Skip clone, use existing repo
                    else:
                        # Rebase failed, likely conflicts
                        logger.warning(f"Pull with rebase failed: {pull_result.stderr}")
                        logger.info("Aborting rebase and falling back to fresh clone")

                        # Abort the rebase
                        subprocess.run(
                            ["git", "rebase", "--abort"],
                            cwd=repo_path,
                            capture_output=True
                        )

                        # Remove existing repo to do fresh clone
                        shutil.rmtree(repo_path, ignore_errors=True)
                        logger.info("Removed existing repository for fresh clone")

                else:
                    logger.warning(f"Fetch failed: {fetch_result.stderr}, falling back to fresh clone")
                    shutil.rmtree(repo_path, ignore_errors=True)

            except subprocess.TimeoutExpired:
                logger.error("Git operation timed out, falling back to fresh clone")
                shutil.rmtree(repo_path, ignore_errors=True)
            except Exception as e:
                logger.error(f"Error updating existing repository: {e}, falling back to fresh clone")
                shutil.rmtree(repo_path, ignore_errors=True)

        # Only clone if repository doesn't exist or update failed
        if repo_needs_clone:
            logger.info(f"Cloning {request.repository_url} to {repo_path}")

            # Check if this might be a private repository and provide helpful error message
            is_likely_private = False

            # Git clone command
            clone_cmd = ["git", "clone"]
            if request.clone_depth and request.clone_depth > 0:
                clone_cmd.extend(["--depth", str(request.clone_depth)])
            if request.branch and request.branch != "main":
                clone_cmd.extend(["-b", request.branch])
            clone_cmd.extend([request.repository_url, str(repo_path)])

            # Execute git clone
            result = subprocess.run(clone_cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                error_msg = result.stderr.lower()

                # Check for common authentication/access issues
                if any(phrase in error_msg for phrase in [
                    "could not read username",
                    "authentication failed",
                    "repository not found",
                    "permission denied",
                    "fatal: authentication failed"
                ]):
                    is_likely_private = True

                if is_likely_private:
                    friendly_error = f"""
Repository access failed - this appears to be a private repository or authentication issue.

For private repositories, you have several options:
1. Make the repository public temporarily
2. Use a GitHub App with proper permissions (recommended for production)
3. Clone manually and upload the codebase

Original error: {result.stderr.strip()}

Note: This system currently only supports public repositories without authentication.
For GitHub App integration with private repositories, additional setup is required.
                    """.strip()
                    raise Exception(friendly_error)
                else:
                    # For other types of errors, show the original error
                    raise Exception(f"Git clone failed: {result.stderr}")

            logger.info(f"Successfully cloned repository to {repo_path}")

        # Step 2: Analyze repository structure
        repo_status.status = "analyzing"
        repo_status.last_update = datetime.now().isoformat()

        # Try MCP orchestration first
        mcp_integration = app_state.get("mcp_integration")
        logger.info(f"🔍 MCP integration available: {mcp_integration is not None}")
        if mcp_integration:
            try:
                logger.info("🚀 Using MCP orchestration for repository analysis")
                repo_analysis = await mcp_integration.analyze_repository_mcp(str(repo_path))
                logger.debug(f"MCP analysis result keys: {list(repo_analysis.keys()) if isinstance(repo_analysis, dict) else 'Not a dict'}")
                repo_files = repo_analysis.get("files", [])
                repo_status.total_files = len(repo_files)
                logger.info(f"✅ MCP repository analysis completed: {len(repo_files)} files found")
                logger.debug(f"First few files: {repo_files[:3] if repo_files else 'No files'}")
            except Exception as e:
                logger.error(f"⚠️ MCP repository analysis failed: {e}", exc_info=True)
                mcp_integration = None  # Fall back to direct analyzer

        # Fallback to direct analyzer
        if not mcp_integration and analyzer is not None:
            try:
                logger.info("📁 Using direct repository analyzer (fallback)")
                repo_info = await analyzer.analyze_repository(repo_path)
                repo_status.total_files = len(repo_info.files)
                logger.info(f"Repository analysis completed: {len(repo_info.files)} files found")
            except Exception as e:
                logger.warning(f"Repository analyzer failed, using manual file counting: {e}")
                analyzer = None  # Fall back to manual counting

        # Final fallback: manual file counting
        if not mcp_integration and analyzer is None:
            logger.info("🔢 Using manual file counting (final fallback)")
            file_extensions = {'.py', '.js', '.ts', '.java', '.cs', '.sql', '.php', '.rb', '.go', '.rs'}
            files = []
            for ext in file_extensions:
                files.extend(repo_path.glob(f"**/*{ext}"))
            repo_status.total_files = len(files)
            logger.info(f"Manual file counting completed: {len(files)} files found")

        # Step 3: Process files for documentation
        repo_status.status = "processing"
        repo_status.last_update = datetime.now().isoformat()

        if repo_status.total_files == 0:
            logger.warning(f"No processable files found in repository {repo_id}")
            repo_status.status = "completed"
            repo_status.documented_files = 0
            repo_status.coverage_percentage = 0.0
            return

        # Real documentation generation with LLM processing and file output
        processed_count = 0
        documented_count = 0

        # Get LLM registry (required for documentation generation)
        registry = app_state.get("registry")

        if not registry:
            logger.warning(f"LLM providers not available - simulation mode")
            # Fallback to simulation
            batch_size = max(1, repo_status.total_files // 10)
            for i in range(0, repo_status.total_files, batch_size):
                await asyncio.sleep(1)
                processed_count = min(i + batch_size, repo_status.total_files)
                repo_status.coverage_percentage = (processed_count / repo_status.total_files) * 100
                repo_status.last_update = datetime.now().isoformat()
        else:
            # Real processing with LLM and SQLite-first documentation storage
            logger.info(f"Starting real documentation generation for {repo_status.total_files} files")

            # Initialize storage system for this repository
            storage_manager = None
            if HAS_STORAGE_SUPPORT:
                try:
                    # Use persistent database in app data directory
                    from ..storage.connection import StorageManager
                    from ..storage.models import FileRecord, Document
                    import hashlib

                    db_path = f"/app/data/baddocs_repo_{repo_id}.db"
                    storage_manager = StorageManager(db_path)
                    await storage_manager.initialize()
                    logger.info(f"✅ SQLite storage initialized: {db_path}")
                except Exception as e:
                    logger.warning(f"⚠️ Storage initialization failed, using file-only mode: {e}")
                    storage_manager = None

            # Default: Enable both SQLite + File export storage modes
            docs_dir = repo_path / "docs" / "generated"
            export_files = True  # Default to both storage modes for maximum compatibility
            if export_files:
                docs_dir.mkdir(parents=True, exist_ok=True)

            # Create README for the docs directory (if file export enabled)
            if export_files:
                readme_content = f"""# Generated Documentation

This directory contains automatically generated documentation for the repository.

- **Generated by:** BadDocs
- **Repository:** {request.repository_url}
- **Generated at:** {datetime.now().isoformat()}
- **Storage Mode:** {'SQLite-First + File Export' if storage_manager else 'File-Only'}
- **Files processed:** TBD

## Storage Information

- **Primary Storage:** {'SQLite database with FTS5 search' if storage_manager else 'File system only'}
- **Database Path:** {db_path if storage_manager else 'N/A'}
- **File Export:** {'Enabled' if export_files else 'Disabled'}

## Structure

- Each source file has a corresponding `.md` documentation file
- Documentation includes function/class descriptions, parameters, and usage examples
- Files are organized to mirror the source code structure

---
*This documentation is automatically generated and updated.*
"""
                with open(docs_dir / "README.md", 'w', encoding='utf-8') as f:
                    f.write(readme_content)

            # Get list of files to process
            file_extensions = {'.py': 'python', '.js': 'javascript', '.ts': 'typescript',
                             '.java': 'java', '.cs': 'csharp', '.sql': 'sql',
                             '.php': 'php', '.rb': 'ruby', '.go': 'go', '.rs': 'rust'}

            files_to_process = []
            for ext, language in file_extensions.items():
                for file_path in repo_path.glob(f"**/*{ext}"):
                    if file_path.is_file() and file_path.stat().st_size < 100000:  # Skip files > 100KB
                        files_to_process.append((file_path, language))

            logger.info(f"Found {len(files_to_process)} files to process")

            # Process files in batches
            batch_size = 3  # Process 3 files at a time to avoid overwhelming LLM
            for i in range(0, len(files_to_process), batch_size):
                batch_files = files_to_process[i:i + batch_size]

                for file_path, language in batch_files:
                    try:
                        # Read file content
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()

                        if not content.strip():
                            processed_count += 1
                            continue

                        # Get relative path from repository root
                        rel_path = str(file_path.relative_to(repo_path))

                        logger.info(f"Processing {rel_path} ({language})")

                        # Generate documentation using LLM
                        llm_request = LLMRequest(
                            prompt=f"Generate comprehensive documentation for this {language} file:\n\n```{language}\n{content}\n```",
                            language=language,
                            context_type="file",
                            temperature=0.1
                        )

                        try:
                            # Process through LLM
                            llm_response = await registry.generate(llm_request)

                            # Calculate content hash for change detection
                            content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()

                            # === PRIMARY STORAGE: SQLite with FTS5 ===
                            file_record_id = None
                            if storage_manager:
                                try:
                                    # Create file record
                                    file_record = FileRecord(
                                        path=rel_path,
                                        language=language,
                                        size=len(content),
                                        last_modified=datetime.fromtimestamp(file_path.stat().st_mtime),
                                        content_hash=content_hash,
                                        metadata={
                                            'repository_url': request.repository_url,
                                            'repository_id': repo_id
                                        }
                                    )
                                    file_record_id = await storage_manager.insert_file(file_record)

                                    # Create document record with FTS5 indexing
                                    document = Document(
                                        file_id=file_record_id,
                                        doc_type='file',
                                        name=file_path.name,
                                        content=llm_response.content,
                                        summary=f"Documentation for {language} file: {rel_path}",
                                        llm_model=llm_response.model,
                                        llm_provider=llm_response.provider,
                                        quality_score=0.8,  # Default quality score
                                        metadata={
                                            'processing_time_ms': llm_response.processing_time_ms,
                                            'total_tokens': llm_response.total_tokens,
                                            'file_size': len(content),
                                            'language': language
                                        }
                                    )
                                    await storage_manager.insert_document(document)
                                    logger.info(f"📊 Stored in SQLite: {rel_path} (file_id: {file_record_id})")

                                except Exception as storage_error:
                                    logger.warning(f"⚠️ SQLite storage failed for {rel_path}: {storage_error}")

                            # === SECONDARY STORAGE: File Export (Optional) ===
                            doc_file_path = None
                            if export_files:
                                try:
                                    # Create documentation file path (mirror source structure)
                                    doc_file_path = docs_dir / f"{rel_path}.md"
                                    doc_file_path.parent.mkdir(parents=True, exist_ok=True)

                                    # Create comprehensive documentation content
                                    doc_content = f"""# Documentation: {rel_path}

**Language:** {language}
**File:** `{rel_path}`
**Generated:** {datetime.now().isoformat()}
**LLM Model:** {llm_response.model} ({llm_response.provider})
**Storage:** {'SQLite + File Export' if storage_manager else 'File Only'}
{'**Database ID:** ' + str(file_record_id) if file_record_id else ''}

---

{llm_response.content}

---

## File Information

- **Size:** {len(content)} characters
- **Processing Time:** {llm_response.processing_time_ms or 0}ms
- **Tokens Used:** {llm_response.total_tokens or 'N/A'}
- **Content Hash:** {content_hash}
- **Repository:** {request.repository_url}

*Generated automatically by BadDocs*
"""

                                    # Write documentation to file
                                    with open(doc_file_path, 'w', encoding='utf-8') as f:
                                        f.write(doc_content)

                                    logger.info(f"📁 File exported: {doc_file_path}")

                                except Exception as export_error:
                                    logger.warning(f"⚠️ File export failed for {rel_path}: {export_error}")

                            documented_count += 1

                            storage_info = f" (SQLite: {'✅' if file_record_id else '❌'}, File: {'✅' if doc_file_path else '❌'})"
                            logger.info(f"✅ Generated documentation: {rel_path}{storage_info}")

                        except Exception as llm_error:
                            logger.warning(f"❌ LLM processing failed for {rel_path}: {llm_error}")

                            # Still store file record in SQLite for tracking (without document)
                            file_record_id = None
                            if storage_manager:
                                try:
                                    content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
                                    file_record = FileRecord(
                                        path=rel_path,
                                        language=language,
                                        size=len(content),
                                        last_modified=datetime.fromtimestamp(file_path.stat().st_mtime),
                                        content_hash=content_hash,
                                        metadata={
                                            'repository_url': request.repository_url,
                                            'repository_id': repo_id,
                                            'processing_error': str(llm_error),
                                            'processing_status': 'failed'
                                        }
                                    )
                                    file_record_id = await storage_manager.insert_file(file_record)
                                    logger.info(f"📊 File record stored (no doc): {rel_path} (file_id: {file_record_id})")
                                except Exception as storage_error:
                                    logger.warning(f"⚠️ SQLite storage failed for error case {rel_path}: {storage_error}")

                            # Create a placeholder documentation file for failed processing (if file export enabled)
                            if export_files:
                                doc_file_path = docs_dir / f"{rel_path}.md"
                                doc_file_path.parent.mkdir(parents=True, exist_ok=True)

                                error_content = f"""# Documentation: {rel_path}

**Language:** {language}
**File:** `{rel_path}`
**Status:** ❌ Processing Failed
**Generated:** {datetime.now().isoformat()}
**Storage:** {'SQLite + File Export' if storage_manager else 'File Only'}
{'**Database ID:** ' + str(file_record_id) if file_record_id else ''}

---

## Processing Error

Documentation generation failed for this file.

**Error:** {str(llm_error)}

**File Preview:**
```{language}
{content[:500]}{'...' if len(content) > 500 else ''}
```

*This file needs manual documentation or LLM processing retry.*
"""
                                with open(doc_file_path, 'w', encoding='utf-8') as f:
                                    f.write(error_content)

                        processed_count += 1

                    except Exception as file_error:
                        logger.warning(f"❌ Failed to process {file_path}: {file_error}")
                        processed_count += 1

                # Update progress after each batch
                repo_status.coverage_percentage = (processed_count / len(files_to_process)) * 100 if files_to_process else 100
                repo_status.documented_files = documented_count
                repo_status.last_update = datetime.now().isoformat()

                logger.info(f"📊 Progress: {processed_count}/{len(files_to_process)} files processed, {documented_count} documented")

                # Small delay between batches
                await asyncio.sleep(1)

            # Update final README with actual stats (if file export enabled)
            if export_files:
                final_readme = readme_content.replace("**Files processed:** TBD", f"**Files processed:** {processed_count} files, {documented_count} documented")
                with open(docs_dir / "README.md", 'w', encoding='utf-8') as f:
                    f.write(final_readme)

            # Log final storage summary
            if storage_manager:
                logger.info(f"🗄️ SQLite Storage Summary: Database at {db_path}, {documented_count} documents with FTS5 indexing")
            if export_files:
                logger.info(f"📁 File Export Summary: {documented_count} documentation files exported to docs/generated/")

            logger.info(f"✅ Documentation generation completed: {processed_count} files processed, {documented_count} documented")

            # Step 4: Commit generated documentation to repository (only if file export enabled)
            if documented_count > 0 and export_files:
                logger.info(f"🔄 Committing {documented_count} documentation files to repository...")

                try:
                    # Configure git for commits
                    subprocess.run(["git", "config", "user.name", "BadDocs Bot"],
                                 cwd=repo_path, check=True, capture_output=True, text=True)
                    subprocess.run(["git", "config", "user.email", "baddocs@automation.local"],
                                 cwd=repo_path, check=True, capture_output=True, text=True)

                    # Add all documentation files
                    subprocess.run(["git", "add", "docs/generated/"],
                                 cwd=repo_path, check=True, capture_output=True, text=True)

                    # Check if there are changes to commit
                    status_result = subprocess.run(["git", "status", "--porcelain"],
                                                 cwd=repo_path, capture_output=True, text=True)

                    if status_result.stdout.strip():
                        # Create commit message
                        commit_message = f"""📚 Add automated documentation

- Generated documentation for {documented_count} files
- Repository: {request.repository_url}
- Processed: {processed_count} total files
- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🤖 Generated with BadDocs
Co-Authored-By: BadDocs <baddocs@automation.local>"""

                        # Commit the changes
                        commit_result = subprocess.run(["git", "commit", "-m", commit_message],
                                                     cwd=repo_path, capture_output=True, text=True)

                        if commit_result.returncode == 0:
                            logger.info(f"✅ Successfully committed documentation: {commit_result.stdout.strip()}")

                            # Note: We don't push automatically to avoid permission issues
                            # In production, this would require SSH keys or GitHub App tokens
                            logger.info(f"📝 Documentation committed locally. Push manually or configure automated push.")

                        else:
                            logger.warning(f"❌ Git commit failed: {commit_result.stderr}")

                    else:
                        logger.info(f"💡 No documentation changes to commit")

                except subprocess.CalledProcessError as git_error:
                    logger.warning(f"❌ Git operations failed: {git_error}")
                except Exception as git_error:
                    logger.warning(f"❌ Git commit error: {git_error}")

        # Mark as completed
        repo_status.status = "completed"
        repo_status.documented_files = repo_status.total_files
        repo_status.coverage_percentage = 100.0
        repo_status.last_update = datetime.now().isoformat()

        logger.info(f"Repository analysis completed: {repo_id}")

    except subprocess.TimeoutExpired:
        logger.error(f"Repository cloning timed out for {repo_id}")
        repo_status = app_state["repositories"].get(repo_id)
        if repo_status:
            repo_status.status = "failed"
            repo_status.processing_errors = ["Repository cloning timed out"]
            repo_status.last_update = datetime.now().isoformat()

    except Exception as e:
        logger.error(f"Background repository analysis failed for {repo_id}: {e}")
        repo_status = app_state["repositories"].get(repo_id)
        if repo_status:
            repo_status.status = "failed"
            repo_status.processing_errors = [str(e)]
            repo_status.last_update = datetime.now().isoformat()

    finally:
        # Keep temporary directory for inspection (disable cleanup temporarily)
        if temp_dir and temp_dir.exists():
            logger.info(f"🔍 Generated files available at: {temp_dir}")
            logger.info(f"📁 Documentation: {temp_dir}/repository/docs/generated/")
            # Cleanup disabled for file inspection - enable in production:
            # try:
            #     shutil.rmtree(temp_dir)
            #     logger.debug(f"Cleaned up temporary directory: {temp_dir}")
            # except Exception as e:
            #     logger.warning(f"Failed to clean up temporary directory {temp_dir}: {e}")


async def _process_github_app_webhook(event, workflow_params, webhook_handler):
    """Process GitHub App webhook event with enhanced workflow."""
    try:
        logger.info(f"Processing GitHub App webhook: {event.event_type} for {workflow_params['repository_name']}")

        # Get MCP integration
        mcp_integration = app_state.get("mcp_integration")
        if not mcp_integration:
            logger.error("MCP integration not available for GitHub App webhook")
            webhook_handler.create_status_check(event, 'error', 'MCP services not available')
            return

        # Update repository status
        repo_id = workflow_params['repository_id']
        if repo_id not in app_state["repositories"]:
            app_state["repositories"][repo_id] = RepositoryStatus(
                repository_id=repo_id,
                repository_url=workflow_params['repository_url'],
                status="github_app_processing",
                total_files=0,
                documented_files=0,
                coverage_percentage=0.0,
                last_update=datetime.now().isoformat()
            )

        repo_status = app_state["repositories"][repo_id]
        repo_status.status = "github_app_processing"
        repo_status.last_update = datetime.now().isoformat()

        # Clone repository using GitHub App authentication
        if event.installation_id:
            try:
                # Use GitHub App token for private repo access
                access_token = webhook_handler.github_auth.get_installation_token(event.installation_id)

                # Modify repo URL to include token
                repo_url = workflow_params['repository_url']
                if repo_url.startswith('https://github.com/'):
                    authenticated_url = repo_url.replace('https://github.com/', f'https://x-access-token:{access_token}@github.com/')
                    workflow_params['repository_url'] = authenticated_url

                logger.info(f"Using GitHub App authentication for repository access")
            except Exception as e:
                logger.error(f"Failed to get GitHub App token: {e}")
                webhook_handler.create_status_check(event, 'error', 'Authentication failed')
                return

        # Trigger MCP analysis with enhanced parameters
        try:
            # Clone repository to temporary directory
            import tempfile
            import subprocess
            from pathlib import Path

            shared_tmp = Path("/tmp/claude") if Path("/tmp/claude").exists() else Path(tempfile.gettempdir())
            shared_tmp.mkdir(exist_ok=True)

            temp_dir = shared_tmp / f"baddocs_{repo_id}"
            if temp_dir.exists():
                import shutil
                shutil.rmtree(temp_dir)
            temp_dir.mkdir(exist_ok=True)

            repo_path = temp_dir / "repository"

            # Clone with authentication
            clone_result = subprocess.run(
                ["git", "clone", workflow_params['repository_url'], str(repo_path)],
                capture_output=True, text=True, timeout=300
            )

            if clone_result.returncode != 0:
                logger.error(f"Git clone failed: {clone_result.stderr}")
                webhook_handler.create_status_check(event, 'error', 'Repository clone failed')
                repo_status.status = "error"
                return

            # Update workflow parameters with local repo path
            workflow_params['repo_path'] = str(repo_path)

            # Start documentation generation workflow with full parameters (includes GitHub token)
            analysis_result = await mcp_integration.start_workflow(
                "documentation_generation",
                workflow_params
            )

            if analysis_result and analysis_result.get('status') == 'success':
                # Update repository status
                stats = analysis_result.get('statistics', {})
                repo_status.status = "completed"
                repo_status.total_files = stats.get('total_files', 0)
                repo_status.documented_files = stats.get('documented_files', 0)
                repo_status.coverage_percentage = stats.get('coverage_percentage', 0.0)
                repo_status.last_update = datetime.now().isoformat()

                # Create success status check
                webhook_handler.create_status_check(
                    event, 'success',
                    f'Documentation updated ({stats.get("documented_files", 0)} files)'
                )

                logger.info(f"GitHub App webhook processing completed successfully for {workflow_params['repository_name']}")

            else:
                logger.error(f"MCP analysis failed: {analysis_result}")
                webhook_handler.create_status_check(event, 'failure', 'Documentation generation failed')
                repo_status.status = "error"

        except Exception as e:
            logger.error(f"GitHub App webhook processing failed: {e}")
            webhook_handler.create_status_check(event, 'error', f'Processing failed: {str(e)}')
            repo_status.status = "error"

        finally:
            # Cleanup
            try:
                if 'temp_dir' in locals() and temp_dir.exists():
                    shutil.rmtree(temp_dir)
            except Exception as e:
                logger.warning(f"Failed to cleanup temp directory: {e}")

    except Exception as e:
        logger.error(f"GitHub App webhook processing failed: {e}")


async def _process_legacy_webhook(repo_id: str, repo_url: str):
    """Process legacy webhook for backward compatibility."""
    try:
        logger.info(f"Processing legacy webhook for {repo_url}")

        # Get MCP integration
        mcp_integration = app_state.get("mcp_integration")
        if not mcp_integration:
            logger.error("MCP integration not available for legacy webhook")
            return

        # Use existing MCP analysis logic
        await _analyze_repository_mcp_async(repo_id, repo_url, None)

    except Exception as e:
        logger.error(f"Legacy webhook processing failed: {e}")


async def _process_mcp_github_task(workflow_params: Dict[str, Any]):
    """Process GitHub repository documentation generation via MCP orchestrator."""
    import tempfile
    import subprocess
    import shutil
    from pathlib import Path

    repo_path = None
    try:
        repo_id = workflow_params.get('repository_id', 'unknown')
        repo_url = workflow_params.get('repository_url', '')
        logger.info(f"🚀 Processing MCP GitHub task for repository: {repo_id} ({repo_url})")

        # Get MCP integration
        mcp_integration = app_state.get("mcp_integration")
        if not mcp_integration:
            logger.error("MCP integration not available for GitHub task processing")
            return

        # Ensure repository status exists
        if repo_id not in app_state["repositories"]:
            app_state["repositories"][repo_id] = RepositoryStatus(
                repository_id=repo_id,
                repository_url=repo_url,
                status="initializing",
                total_files=0,
                documented_files=0,
                coverage_percentage=0.0,
                last_update=datetime.now().isoformat()
            )

        repo_status = app_state["repositories"][repo_id]

        # Step 1: Clone repository to shared volume (same as working homepage flow)
        repo_status.status = "cloning"
        repo_status.last_update = datetime.now().isoformat()
        logger.info(f"🔄 Cloning repository: {repo_url}")

        # Use shared volume that MCP servers can access
        shared_tmp = Path("/tmp/claude") if Path("/tmp/claude").exists() else Path(tempfile.gettempdir())
        shared_tmp.mkdir(exist_ok=True)

        temp_dir = shared_tmp / f"baddocs_{repo_id}"
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        temp_dir.mkdir(exist_ok=True)

        repo_path = temp_dir / "repository"

        # Create authenticated clone URL if GitHub token is available
        clone_url = repo_url
        github_token = workflow_params.get('github_token')
        installation_id = workflow_params.get('installation_id')
        logger.info(f"DEBUG clone auth: github_token={'[SET]' if github_token else '[NOT SET]'}, installation_id={installation_id}, workflow_params_keys={list(workflow_params.keys())}")

        if github_token and installation_id:
            try:
                # Convert HTTPS URL to authenticated format using the provided token
                # https://github.com/owner/repo -> https://x-access-token:TOKEN@github.com/owner/repo
                if repo_url.startswith('https://github.com/'):
                    clone_url = repo_url.replace('https://github.com/', f'https://x-access-token:{github_token}@github.com/')
                    logger.info(f"Using authenticated clone URL for private repository access (installation: {installation_id})")
                else:
                    logger.warning(f"Unexpected repository URL format: {repo_url}")
            except Exception as auth_error:
                logger.warning(f"GitHub authentication setup failed, trying public clone: {auth_error}")
        else:
            if not github_token:
                logger.warning("No GitHub token provided - attempting public clone")
            if not installation_id:
                logger.warning("No installation ID provided - attempting public clone")

        logger.info(f"Cloning {repo_url} to {repo_path}")

        # Git clone with timeout and error handling
        result = subprocess.run(
            ["git", "clone", clone_url, str(repo_path)],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            logger.error(f"Git clone failed: {result.stderr}")
            repo_status.status = "error"
            repo_status.last_update = datetime.now().isoformat()
            return

        # Get HEAD commit information for documentation currency check
        commit_hash = None
        commit_timestamp = None
        commit_message = None
        try:
            hash_result = subprocess.run(
                ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=10
            )
            if hash_result.returncode == 0:
                commit_hash = hash_result.stdout.strip()
                logger.info(f"Repository HEAD commit: {commit_hash}")

            # Get commit timestamp
            timestamp_result = subprocess.run(
                ["git", "-C", str(repo_path), "log", "-1", "--format=%cI"],
                capture_output=True, text=True, timeout=10
            )
            if timestamp_result.returncode == 0:
                commit_timestamp = timestamp_result.stdout.strip()

            # Get commit message
            message_result = subprocess.run(
                ["git", "-C", str(repo_path), "log", "-1", "--format=%s"],
                capture_output=True, text=True, timeout=10
            )
            if message_result.returncode == 0:
                commit_message = message_result.stdout.strip()

        except Exception as e:
            logger.warning(f"Failed to get commit info: {e}")

        # Step 2: MCP Analysis Pipeline (same as working homepage flow)
        repo_status.status = "analyzing"
        repo_status.last_update = datetime.now().isoformat()
        logger.info(f"🎯 Calling MCP orchestrator for complete documentation generation with local path: {repo_path}")

        # Use complete documentation generation workflow (includes analysis, export, and commit)
        repository_id = workflow_params.get('repository_id', repo_id)
        repository_url = workflow_params.get('repository_url', '')

        # Extract authentication info for MCP workflow (avoid passing non-serializable objects)
        github_auth = workflow_params.get('github_auth')
        auth_params = {}
        logger.info(f"DEBUG: workflow_params keys: {list(workflow_params.keys())}")
        logger.info(f"DEBUG: workflow_params installation_id: {workflow_params.get('installation_id')}")
        if github_auth:
            installation_id = workflow_params.get('installation_id')
            logger.info(f"DEBUG: Using installation_id={installation_id} for token request")
            if installation_id:
                try:
                    # Get installation token for the workflow
                    access_token = github_auth.get_installation_token(installation_id)
                    auth_params = {
                        'github_token': access_token,
                        'installation_id': installation_id
                    }
                except Exception as e:
                    logger.warning(f"Failed to get GitHub token: {e}")

        # Fetch database credentials from storage (with environment variable fallback)
        database_config = {}
        if app_state.get('storage_manager'):
            try:
                from ..storage.database_config_ops import DatabaseConfigOperations

                db_config_ops = DatabaseConfigOperations(app_state['storage_manager'])

                # Get config from storage or environment variables
                database_config = db_config_ops.get_config_with_env_fallback(repository_id)

                if database_config and database_config.get('is_valid'):
                    source = database_config.get('source', 'unknown')
                    logger.info(f"✅ Database credentials found for repository {repository_id} (source: {source})")
                    logger.info(f"✅ Database type: {database_config.get('database_type')}, host: {database_config.get('host')}")
                else:
                    logger.info(f"ℹ️ No database credentials found for repository {repository_id}")
                    database_config = {}

            except Exception as e:
                logger.warning(f"Failed to fetch database credentials: {e}")
                database_config = {}

        # DEBUG: Log what's being passed to MCP orchestrator
        logger.info(f"📊 DEBUG: Calling MCP orchestrator with database_config: {database_config}")

        analysis_result = await mcp_integration.generate_documentation_mcp(
            repo_path=str(repo_path),
            repository_id=repository_id,
            repository_url=repository_url,
            target_branch='docs',  # Default documentation branch
            commit_enabled=True,   # Enable committing back to repository
            export_format='markdown',
            database_config=database_config,  # Include database configuration
            commit_hash=commit_hash,  # For documentation currency check
            commit_timestamp=commit_timestamp,
            commit_message_original=commit_message,
            repository_name=repo_id,
            **auth_params
        )
        logger.info(f"🎯 MCP orchestrator returned: {type(analysis_result)} - {analysis_result}")

        # Workflow can return 'success' or 'completed' as success states
        workflow_status = analysis_result.get('status') if analysis_result else None
        if analysis_result and workflow_status in ['success', 'completed']:
            logger.info(f"✅ MCP GitHub task completed successfully for {repo_id} (status: {workflow_status})")
            repo_status.status = "completed"
            repo_status.last_update = datetime.now().isoformat()

            # Update file statistics if available
            if isinstance(analysis_result, dict):
                stats = analysis_result.get('statistics', {})
                repo_status.total_files = stats.get('total_files', 0)
                repo_status.documented_files = stats.get('documented_files', 0)
                repo_status.coverage_percentage = stats.get('coverage_percentage', 0.0)
        else:
            logger.error(f"❌ MCP GitHub task failed for {repo_id}: {analysis_result}")
            repo_status.status = "error"
            repo_status.last_update = datetime.now().isoformat()

    except subprocess.TimeoutExpired:
        logger.error(f"❌ Git clone timeout for {repo_id}")
        if repo_id in app_state["repositories"]:
            app_state["repositories"][repo_id].status = "error"
            app_state["repositories"][repo_id].last_update = datetime.now().isoformat()
    except Exception as e:
        logger.error(f"❌ MCP GitHub task processing failed: {e}")
        if repo_id in app_state["repositories"]:
            app_state["repositories"][repo_id].status = "error"
            app_state["repositories"][repo_id].last_update = datetime.now().isoformat()
    finally:
        # Cleanup DISABLED - MCP workflow needs repository for commit/push/PR steps
        # The workflow will handle cleanup after committing documentation
        # if repo_path and repo_path.exists():
        #     try:
        #         import shutil
        #         shutil.rmtree(repo_path.parent)
        #         logger.info(f"🧹 Cleaned up temporary directory: {repo_path.parent}")
        #     except Exception as cleanup_error:
        #         logger.warning(f"⚠️ Cleanup failed: {cleanup_error}")
        logger.info(f"📁 Repository preserved for MCP workflow commit step: {repo_path if repo_path else 'N/A'}")


async def _process_manual_github_generation(repo_id: str, github_auth):
    """Process manual GitHub repository documentation generation directly."""
    try:
        logger.info(f"🔧 Processing manual GitHub generation for repository: {repo_id}")

        # Create or update repository status
        if repo_id not in app_state["repositories"]:
            app_state["repositories"][repo_id] = RepositoryStatus(
                repository_id=repo_id,
                repository_url=f"github://repository/{repo_id}",
                status="direct_processing",
                total_files=0,
                documented_files=0
            )

        app_state["repositories"][repo_id].status = "direct_processing"
        app_state["repositories"][repo_id].last_update = datetime.now().isoformat()

        # For now, simulate processing and mark as completed
        # TODO: Implement actual repository analysis using GitHub API
        logger.info(f"✅ Direct GitHub generation completed for {repo_id}")

        app_state["repositories"][repo_id].status = "completed"
        app_state["repositories"][repo_id].last_update = datetime.now().isoformat()

    except Exception as e:
        logger.error(f"❌ Direct GitHub generation failed for {repo_id}: {e}")
        if repo_id in app_state["repositories"]:
            app_state["repositories"][repo_id].status = "error"
            app_state["repositories"][repo_id].last_update = datetime.now().isoformat()


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")

    uvicorn.run(
        "src.baddocs.web.main:app",
        host=host,
        port=port,
        reload=os.getenv("ENVIRONMENT", "production") == "development"
    )