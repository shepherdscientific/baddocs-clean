"""
Web routes for database configuration management.

Provides endpoints for storing, retrieving, and testing repository-specific
database credentials through a web UI.
"""

import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from ..storage.database_config_ops import DatabaseConfigOperations, DatabaseConfig

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/github", tags=["database-config"])

# Setup templates
templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


def init_database_config_routes(app, storage_manager, github_app_auth=None):
    """
    Initialize database configuration routes.

    Args:
        app: FastAPI application instance
        storage_manager: Storage manager for database operations
        github_app_auth: Optional GitHub App authentication handler
    """
    db_config_ops = DatabaseConfigOperations(storage_manager)

    @app.get("/github/database-config/{repository_id}", response_class=HTMLResponse)
    async def database_config_form(request: Request, repository_id: str, installation_id: Optional[int] = None):
        """
        Display database configuration form for a repository.

        Args:
            request: FastAPI request
            repository_id: GitHub repository ID
            installation_id: GitHub installation ID (optional)

        Returns:
            HTML form for database configuration
        """
        try:
            # Get repository name from GitHub API if available
            repository_name = f"Repository {repository_id}"
            if github_app_auth and installation_id:
                try:
                    token = await github_app_auth.get_installation_token(installation_id)
                    # Fetch repo info from GitHub
                    import httpx
                    async with httpx.AsyncClient() as client:
                        response = await client.get(
                            f"https://api.github.com/repositories/{repository_id}",
                            headers={
                                "Authorization": f"token {token}",
                                "Accept": "application/vnd.github.v3+json"
                            }
                        )
                        if response.status_code == 200:
                            repo_data = response.json()
                            repository_name = repo_data.get('full_name', repository_name)
                except Exception as e:
                    logger.warning(f"Could not fetch repository name: {e}")

            # Get existing configuration if any
            existing_config = db_config_ops.get_config(repository_id)

            return templates.TemplateResponse("database_config.html", {
                "request": request,
                "repository_id": repository_id,
                "repository_name": repository_name,
                "installation_id": installation_id,
                "existing_config": existing_config,
                "message": None,
                "message_type": None
            })

        except Exception as e:
            logger.error(f"Failed to display database config form: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/github/database-config/{repository_id}", response_class=HTMLResponse)
    async def save_database_config(
        request: Request,
        repository_id: str,
        database_type: str = Form(...),
        host: str = Form(...),
        port: int = Form(...),
        database_name: str = Form(...),
        username: str = Form(...),
        password: str = Form(...),
        ssl_enabled: bool = Form(False),
        installation_id: Optional[int] = Form(None)
    ):
        """
        Save database configuration for a repository.

        Args:
            request: FastAPI request
            repository_id: GitHub repository ID
            database_type: Type of database (mysql, postgresql, etc.)
            host: Database host
            port: Database port
            database_name: Database name
            username: Database username
            password: Database password (will be encrypted)
            ssl_enabled: Whether SSL is enabled
            installation_id: GitHub installation ID (optional)

        Returns:
            HTML form with success/error message
        """
        try:
            # Create database config
            config = DatabaseConfig(
                repository_id=repository_id,
                database_type=database_type,
                host=host,
                port=port,
                database_name=database_name,
                username=username,
                password=password,
                ssl_enabled=ssl_enabled
            )

            # Store configuration
            success = db_config_ops.store_config(config)

            if success:
                message = "✅ Database configuration saved successfully!"
                message_type = "success"
                logger.info(f"Saved database config for repository {repository_id}")
            else:
                message = "❌ Failed to save database configuration"
                message_type = "error"

            # Get repository name
            repository_name = f"Repository {repository_id}"
            if github_app_auth and installation_id:
                try:
                    token = await github_app_auth.get_installation_token(installation_id)
                    import httpx
                    async with httpx.AsyncClient() as client:
                        response = await client.get(
                            f"https://api.github.com/repositories/{repository_id}",
                            headers={
                                "Authorization": f"token {token}",
                                "Accept": "application/vnd.github.v3+json"
                            }
                        )
                        if response.status_code == 200:
                            repo_data = response.json()
                            repository_name = repo_data.get('full_name', repository_name)
                except Exception as e:
                    logger.warning(f"Could not fetch repository name: {e}")

            # Get updated configuration
            existing_config = db_config_ops.get_config(repository_id)

            return templates.TemplateResponse("database_config.html", {
                "request": request,
                "repository_id": repository_id,
                "repository_name": repository_name,
                "installation_id": installation_id,
                "existing_config": existing_config,
                "message": message,
                "message_type": message_type
            })

        except Exception as e:
            logger.error(f"Failed to save database config: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/github/database-config/{repository_id}/test")
    async def test_database_connection(
        repository_id: str,
        request: Request
    ):
        """
        Test database connection with provided credentials.

        Args:
            repository_id: GitHub repository ID
            request: FastAPI request containing connection details

        Returns:
            JSON response with test result
        """
        try:
            # Parse request body
            body = await request.json()

            # For now, just validate that all required fields are present
            required_fields = ['database_type', 'host', 'port', 'database_name', 'username', 'password']
            missing_fields = [field for field in required_fields if field not in body]

            if missing_fields:
                return JSONResponse({
                    "success": False,
                    "error": f"Missing required fields: {', '.join(missing_fields)}"
                })

            # TODO: Actually test the database connection
            # For now, just return success if fields are valid
            logger.info(f"Database connection test requested for {repository_id}: {body['database_type']} @ {body['host']}")

            return JSONResponse({
                "success": True,
                "message": "Connection parameters validated (actual connection test not yet implemented)"
            })

        except Exception as e:
            logger.error(f"Failed to test database connection: {e}")
            return JSONResponse({
                "success": False,
                "error": str(e)
            })

    @app.delete("/github/database-config/{repository_id}")
    async def delete_database_config(repository_id: str):
        """
        Delete database configuration for a repository.

        Args:
            repository_id: GitHub repository ID

        Returns:
            JSON response with deletion result
        """
        try:
            success = db_config_ops.delete_config(repository_id)

            if success:
                logger.info(f"Deleted database config for repository {repository_id}")
                return JSONResponse({"success": True, "message": "Configuration deleted"})
            else:
                return JSONResponse({"success": False, "error": "Configuration not found"})

        except Exception as e:
            logger.error(f"Failed to delete database config: {e}")
            return JSONResponse({"success": False, "error": str(e)})

    @app.get("/api/github/database-config/{repository_id}")
    async def get_database_config_api(repository_id: str):
        """
        API endpoint to get database configuration (without password).

        Args:
            repository_id: GitHub repository ID

        Returns:
            JSON response with configuration details
        """
        try:
            config = db_config_ops.get_config(repository_id)

            if config:
                return JSONResponse({
                    "repository_id": config.repository_id,
                    "database_type": config.database_type,
                    "host": config.host,
                    "port": config.port,
                    "database_name": config.database_name,
                    "username": config.username,
                    "ssl_enabled": config.ssl_enabled,
                    "has_password": True,
                    "created_at": config.created_at.isoformat() if config.created_at else None,
                    "updated_at": config.updated_at.isoformat() if config.updated_at else None,
                    "last_tested_at": config.last_tested_at.isoformat() if config.last_tested_at else None
                })
            else:
                return JSONResponse({"has_config": False})

        except Exception as e:
            logger.error(f"Failed to get database config: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    logger.info("Database configuration routes initialized")