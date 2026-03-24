"""
MCP integration layer for BadDocs Web API.

Provides integration between the FastAPI web service and the MCP server orchestrator,
replacing direct imports with proper MCP protocol communication.
"""

import asyncio
import logging
import httpx
from typing import Dict, Any, Optional, List
from pathlib import Path

logger = logging.getLogger(__name__)


class MCPClientError(Exception):
    """Exception raised when MCP communication fails."""
    pass


class MCPOrchestrationClient:
    """
    Client for communicating with BadDocs MCP server orchestrator.

    Handles request routing, server discovery, and error handling
    for web API integration with MCP servers.
    """

    def __init__(self, orchestrator_url: str = "http://localhost:8001"):
        """
        Initialize MCP orchestration client.

        Args:
            orchestrator_url: Base URL of the MCP Core server
        """
        self.orchestrator_url = orchestrator_url.rstrip('/')
        self.client = httpx.AsyncClient(timeout=300.0)  # 5 minute timeout for long operations
        self.logger = logging.getLogger(__name__)

    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    async def health_check(self) -> Dict[str, Any]:
        """Check health of MCP orchestrator and servers."""
        try:
            self.logger.info(f"Attempting MCP health check to: {self.orchestrator_url}/health")
            response = await self.client.get(f"{self.orchestrator_url}/health")
            self.logger.info(f"MCP health check response: {response.status_code}")
            response.raise_for_status()
            result = response.json()
            self.logger.info(f"MCP health check successful: {result}")
            return result
        except Exception as e:
            self.logger.error(f"MCP health check failed: {e}")
            self.logger.error(f"Exception type: {type(e)}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return {"status": "unhealthy", "error": str(e)}

    async def get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status from MCP orchestrator."""
        try:
            response = await self.client.get(f"{self.orchestrator_url}/status")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.error(f"Failed to get system status: {e}")
            raise MCPClientError(f"System status request failed: {e}")

    async def list_servers(self) -> Dict[str, Any]:
        """List available MCP servers."""
        try:
            response = await self.client.get(f"{self.orchestrator_url}/servers")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.error(f"Failed to list servers: {e}")
            raise MCPClientError(f"Server list request failed: {e}")

    async def generate_documentation(
        self,
        repo_path: str,
        output_format: str = "markdown",
        include_legacy: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generate documentation for repository via MCP orchestrator.

        Args:
            repo_path: Path to repository
            output_format: Output format (markdown, html, json)
            include_legacy: Include legacy language processing

        Returns:
            Documentation generation results
        """
        try:
            request_data = {
                "jsonrpc": "2.0",
                "id": "doc_gen_1",
                "method": "generate_documentation",
                "params": {
                    "repo_path": repo_path,
                    "output_format": output_format,
                    "include_legacy": include_legacy,
                    **kwargs
                }
            }

            response = await self.client.post(
                f"{self.orchestrator_url}/mcp",
                json=request_data
            )
            response.raise_for_status()

            result = response.json()
            if "error" in result:
                raise MCPClientError(f"MCP error: {result['error']}")

            return result.get("result", {})

        except Exception as e:
            self.logger.error(f"Documentation generation failed: {e}")
            raise MCPClientError(f"Documentation generation failed: {e}")

    async def analyze_repository(self, repo_path: str, **kwargs) -> Dict[str, Any]:
        """
        Analyze repository structure via MCP Git server.

        Args:
            repo_path: Path to repository

        Returns:
            Repository analysis results
        """
        try:
            request_data = {
                "jsonrpc": "2.0",
                "id": "repo_analysis_1",
                "method": "analyze_repository",
                "params": {
                    "repo_path": repo_path,
                    **kwargs
                }
            }

            response = await self.client.post(
                f"{self.orchestrator_url}/mcp",
                json=request_data
            )
            response.raise_for_status()

            result = response.json()
            self.logger.info(f"MCP analyze_repository response structure: {list(result.keys()) if isinstance(result, dict) else 'Not a dict'}")
            self.logger.debug(f"Full MCP response: {result}")

            if "error" in result:
                raise MCPClientError(f"MCP error: {result['error']}")

            mcp_result = result.get("result", {})
            self.logger.info(f"MCP result keys: {list(mcp_result.keys()) if isinstance(mcp_result, dict) else 'Not a dict'}")
            self.logger.info(f"Files found in MCP result: {len(mcp_result.get('files', []))}")

            return mcp_result

        except Exception as e:
            self.logger.error(f"Repository analysis failed: {e}")
            raise MCPClientError(f"Repository analysis failed: {e}")

    async def process_incremental_changes(
        self,
        repo_path: str,
        since_commit: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Process incremental changes via MCP orchestrator.

        Args:
            repo_path: Path to repository
            since_commit: Process changes since this commit

        Returns:
            Incremental processing results
        """
        try:
            request_data = {
                "jsonrpc": "2.0",
                "id": "incremental_1",
                "method": "process_incremental_changes",
                "params": {
                    "repo_path": repo_path,
                    "since_commit": since_commit,
                    **kwargs
                }
            }

            response = await self.client.post(
                f"{self.orchestrator_url}/mcp",
                json=request_data
            )
            response.raise_for_status()

            result = response.json()
            if "error" in result:
                raise MCPClientError(f"MCP error: {result['error']}")

            return result.get("result", {})

        except Exception as e:
            self.logger.error(f"Incremental processing failed: {e}")
            raise MCPClientError(f"Incremental processing failed: {e}")

    async def detect_languages(self, files: List[str]) -> Dict[str, Any]:
        """
        Detect programming languages via MCP Language server.

        Args:
            files: List of file paths

        Returns:
            Language detection results
        """
        try:
            request_data = {
                "jsonrpc": "2.0",
                "id": "lang_detect_1",
                "method": "route_request",
                "params": {
                    "method": "detect_languages",
                    "params": {"files": files}
                }
            }

            response = await self.client.post(
                f"{self.orchestrator_url}/mcp",
                json=request_data
            )
            response.raise_for_status()

            result = response.json()
            if "error" in result:
                raise MCPClientError(f"MCP error: {result['error']}")

            return result.get("result", {})

        except Exception as e:
            self.logger.error(f"Language detection failed: {e}")
            raise MCPClientError(f"Language detection failed: {e}")

    async def process_files_via_llm(
        self,
        files: List[str],
        language_map: Dict[str, str],
        **kwargs
    ) -> Dict[str, Any]:
        """
        Process files through LLM via MCP LLM server.

        Args:
            files: List of file paths to process
            language_map: Mapping of files to detected languages

        Returns:
            LLM processing results
        """
        try:
            request_data = {
                "jsonrpc": "2.0",
                "id": "llm_process_1",
                "method": "route_request",
                "params": {
                    "method": "process_files",
                    "params": {
                        "files": files,
                        "language_map": language_map,
                        **kwargs
                    }
                }
            }

            response = await self.client.post(
                f"{self.orchestrator_url}/mcp",
                json=request_data
            )
            response.raise_for_status()

            result = response.json()
            if "error" in result:
                raise MCPClientError(f"MCP error: {result['error']}")

            return result.get("result", {})

        except Exception as e:
            self.logger.error(f"LLM file processing failed: {e}")
            raise MCPClientError(f"LLM file processing failed: {e}")

    async def store_documentation(
        self,
        file_records: List[Dict[str, Any]],
        documents: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Store documentation via MCP Storage server.

        Args:
            file_records: File records to store
            documents: Document records to store

        Returns:
            Storage operation results
        """
        try:
            request_data = {
                "jsonrpc": "2.0",
                "id": "storage_1",
                "method": "route_request",
                "params": {
                    "method": "batch_store_documents",
                    "params": {
                        "file_records": file_records,
                        "documents": documents
                    }
                }
            }

            response = await self.client.post(
                f"{self.orchestrator_url}/mcp",
                json=request_data
            )
            response.raise_for_status()

            result = response.json()
            if "error" in result:
                raise MCPClientError(f"MCP error: {result['error']}")

            return result.get("result", {})

        except Exception as e:
            self.logger.error(f"Documentation storage failed: {e}")
            raise MCPClientError(f"Documentation storage failed: {e}")

    async def search_documentation(
        self,
        query: str,
        repository_filter: Optional[str] = None,
        doc_type_filter: Optional[str] = None,
        language_filter: Optional[str] = None,
        limit: int = 20
    ) -> Dict[str, Any]:
        """
        Search documentation via MCP Storage server FTS5.

        Args:
            query: Search query
            repository_filter: Filter by repository
            doc_type_filter: Filter by document type
            language_filter: Filter by programming language
            limit: Maximum results to return

        Returns:
            Search results
        """
        try:
            request_data = {
                "jsonrpc": "2.0",
                "id": "search_1",
                "method": "route_request",
                "params": {
                    "method": "search_documents",
                    "params": {
                        "query": query,
                        "repository_filter": repository_filter,
                        "doc_type_filter": doc_type_filter,
                        "language_filter": language_filter,
                        "limit": limit
                    }
                }
            }

            response = await self.client.post(
                f"{self.orchestrator_url}/mcp",
                json=request_data
            )
            response.raise_for_status()

            result = response.json()
            if "error" in result:
                raise MCPClientError(f"MCP error: {result['error']}")

            return result.get("result", {})

        except Exception as e:
            self.logger.error(f"Documentation search failed: {e}")
            raise MCPClientError(f"Documentation search failed: {e}")

    async def start_workflow(
        self,
        workflow_name: str,
        params: Dict[str, Any],
        execution_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Start a workflow execution via MCP Core server.

        Args:
            workflow_name: Name of workflow to execute
            params: Workflow parameters
            execution_id: Optional execution ID

        Returns:
            Workflow execution information
        """
        try:
            request_data = {
                "jsonrpc": "2.0",
                "id": "workflow_start_1",
                "method": "start_workflow",
                "params": {
                    "workflow_name": workflow_name,
                    "params": params,
                    "execution_id": execution_id
                }
            }

            response = await self.client.post(
                f"{self.orchestrator_url}/mcp",
                json=request_data
            )
            response.raise_for_status()

            result = response.json()
            if "error" in result:
                raise MCPClientError(f"MCP error: {result['error']}")

            return result.get("result", {})

        except Exception as e:
            self.logger.error(f"Workflow start failed: {e}")
            raise MCPClientError(f"Workflow start failed: {e}")

    async def get_workflow_status(self, execution_id: str) -> Dict[str, Any]:
        """Get workflow execution status."""
        try:
            response = await self.client.get(
                f"{self.orchestrator_url}/workflows/{execution_id}"
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.error(f"Failed to get workflow status: {e}")
            raise MCPClientError(f"Workflow status request failed: {e}")

    async def list_workflows(
        self,
        status_filter: Optional[str] = None,
        limit: int = 100
    ) -> Dict[str, Any]:
        """List workflow executions."""
        try:
            params = {}
            if status_filter:
                params["status_filter"] = status_filter
            if limit != 100:
                params["limit"] = limit

            url = f"{self.orchestrator_url}/workflows"
            if params:
                query_string = "&".join(f"{k}={v}" for k, v in params.items())
                url += f"?{query_string}"

            response = await self.client.get(url)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.error(f"Failed to list workflows: {e}")
            raise MCPClientError(f"Workflow list request failed: {e}")


class MCPWebIntegration:
    """
    Integration wrapper for using MCP services from BadDocs Web API.

    Provides high-level methods that mirror the original direct import
    functionality but route through MCP servers.
    """

    def __init__(self, orchestrator_url: str = "http://localhost:8001"):
        """
        Initialize MCP web integration.

        Args:
            orchestrator_url: URL of MCP Core server orchestrator
        """
        self.orchestrator_url = orchestrator_url
        self.client = MCPOrchestrationClient(orchestrator_url)
        self.logger = logging.getLogger(__name__)

    async def initialize(self, max_retries: int = 5, retry_delay: float = 5.0) -> bool:
        """
        Initialize MCP integration and check server availability with retry logic.

        Args:
            max_retries: Maximum number of retry attempts
            retry_delay: Delay between retries in seconds

        Returns:
            True if initialization successful, False otherwise
        """
        import asyncio

        for attempt in range(max_retries):
            try:
                self.logger.info(f"MCP initialization attempt {attempt + 1}/{max_retries}")

                # Check orchestrator health
                health = await self.client.health_check()
                if health.get("status") != "healthy":
                    self.logger.warning(f"MCP orchestrator unhealthy (attempt {attempt + 1}): {health}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                        continue
                    return False

                # Check available servers
                servers = await self.client.list_servers()
                available_servers = servers.get("servers", {})

                required_servers = ["git", "llm", "language"]  # core is the orchestrator itself
                missing_servers = [s for s in required_servers if s not in available_servers]

                if missing_servers:
                    self.logger.warning(f"Missing required MCP servers (attempt {attempt + 1}): {missing_servers}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                        continue
                    return False

                self.logger.info(f"MCP integration initialized successfully with {len(available_servers)} servers")
                return True

            except Exception as e:
                self.logger.error(f"MCP initialization attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    self.logger.info(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 1.5  # Exponential backoff
                    continue
                else:
                    self.logger.error(f"MCP integration initialization failed after {max_retries} attempts")
                    return False

        return False

    async def close(self):
        """Close MCP integration."""
        await self.client.close()

    async def __aenter__(self):
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    async def analyze_repository_mcp(self, repo_path: str) -> Dict[str, Any]:
        """
        Analyze repository using MCP Git server.

        Replaces direct RepositoryAnalyzer import.
        """
        try:
            result = await self.client.analyze_repository(repo_path)
            return result
        except MCPClientError:
            # Fallback to basic file scanning if MCP unavailable
            self.logger.warning("MCP repository analysis failed, using fallback")
            return await self._fallback_repository_analysis(repo_path)

    async def _fallback_repository_analysis(self, repo_path: str) -> Dict[str, Any]:
        """Fallback repository analysis when MCP unavailable."""
        try:
            repo_path = Path(repo_path)
            if not repo_path.exists():
                return {"error": "Repository path does not exist", "files": []}

            # Simple file extension analysis
            file_extensions = {'.py', '.js', '.ts', '.java', '.cs', '.sql', '.php', '.rb', '.go', '.rs'}
            files = []

            for ext in file_extensions:
                for file_path in repo_path.glob(f"**/*{ext}"):
                    if file_path.is_file() and file_path.stat().st_size < 100000:
                        files.append({
                            "path": str(file_path.relative_to(repo_path)),
                            "size": file_path.stat().st_size,
                            "language": self._detect_language_from_extension(ext)
                        })

            return {
                "repository": str(repo_path),
                "files": files,
                "analysis": {"total_files": len(files), "fallback_mode": True}
            }

        except Exception as e:
            self.logger.error(f"Fallback repository analysis failed: {e}")
            return {"error": str(e), "files": []}

    def _detect_language_from_extension(self, ext: str) -> str:
        """Simple language detection from file extension."""
        mapping = {
            '.py': 'python', '.pyw': 'python', '.pyi': 'python',
            '.js': 'javascript', '.mjs': 'javascript', '.jsx': 'javascript',
            '.ts': 'typescript', '.tsx': 'typescript', '.cjs': 'javascript',
            '.java': 'java',
            '.cs': 'csharp',
            '.sql': 'sql',
            '.php': 'php', '.phtml': 'php', '.php3': 'php', '.php4': 'php', '.php5': 'php', '.phps': 'php',
            '.rb': 'ruby', '.rake': 'ruby', '.gemspec': 'ruby', '.ru': 'ruby',
            '.go': 'go',
            '.rs': 'rust',
            '.cbl': 'cobol', '.cob': 'cobol', '.cpy': 'cobol', '.pco': 'cobol', '.cobol': 'cobol',
            '.f': 'fortran', '.f77': 'fortran', '.f90': 'fortran', '.f95': 'fortran', '.for': 'fortran', '.ftn': 'fortran',
            '.bas': 'vb6', '.frm': 'vb6', '.cls': 'vb6', '.ctl': 'vb6', '.pag': 'vb6', '.dob': 'vb6', '.vb': 'vb6',
            '.pbl': 'powerbuilder', '.pbt': 'powerbuilder', '.pbw': 'powerbuilder', '.srd': 'powerbuilder', '.sru': 'powerbuilder', '.srw': 'powerbuilder', '.pbd': 'powerbuilder',
            '.r': 'r', '.R': 'r', '.Rmd': 'r', '.Rnw': 'r', '.Rscript': 'r'
        }
        return mapping.get(ext, 'unknown')

    async def generate_documentation_mcp(
        self,
        repo_path: str,
        repository_id: str,
        repository_url: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generate repository documentation using MCP workflow orchestration.

        Replaces direct LLM provider calls and storage operations.
        """
        try:
            # Start documentation generation workflow
            workflow_params = {
                "repo_path": repo_path,
                "repository_id": repository_id,
                "repository_url": repository_url,
                "output_format": "markdown",
                "include_legacy": True,
                "storage_mode": "sqlite_first_with_export",
                **kwargs
            }

            workflow_result = await self.client.start_workflow(
                "documentation_generation",
                workflow_params
            )

            return workflow_result

        except MCPClientError as e:
            self.logger.error(f"MCP documentation generation failed: {e}")
            raise

    async def search_documentation_mcp(
        self,
        query: str,
        repository_filter: Optional[str] = None,
        doc_type_filter: Optional[str] = None,
        language_filter: Optional[str] = None,
        limit: int = 20
    ) -> Dict[str, Any]:
        """
        Search documentation using MCP Storage server FTS5.

        Replaces direct SearchEngine calls.
        """
        try:
            return await self.client.search_documentation(
                query=query,
                repository_filter=repository_filter,
                doc_type_filter=doc_type_filter,
                language_filter=language_filter,
                limit=limit
            )
        except MCPClientError as e:
            self.logger.error(f"MCP documentation search failed: {e}")
            raise

    def get_system_health(self) -> Dict[str, Any]:
        """Get MCP system health status."""
        return asyncio.create_task(self.client.get_system_status())