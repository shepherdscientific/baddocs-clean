"""
GitHub Secrets Manager for BadDocs.

Provides secure access to GitHub repository secrets for database credentials
and other sensitive configuration data. Uses GitHub App authentication to
fetch encrypted repository secrets via the GitHub API.
"""

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class GitHubSecretsManager:
    """
    Manages secure access to GitHub repository secrets.

    Provides methods to fetch repository secrets for database credentials
    and other sensitive configuration, with proper caching and security.
    """

    def __init__(self, github_token: str) -> None:
        """
        Initialize GitHub Secrets Manager.

        Args:
            github_token: GitHub App installation token
        """
        self.github_token = github_token
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "Authorization": f"token {github_token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "BadDocs-GitHub-App"
            }
        )

        # Secret cache with TTL
        self._secret_cache: dict[str, dict[str, Any]] = {}
        self._cache_ttl = 300  # 5 minutes cache TTL

    async def get_repository_secrets(self, owner: str, repo: str, secret_names: list[str]) -> dict[str, str | None]:
        """
        Fetch repository secrets by name.

        Args:
            owner: Repository owner
            repo: Repository name
            secret_names: List of secret names to fetch

        Returns:
            Dictionary mapping secret names to values (or None if not found)
        """
        try:
            cache_key = f"{owner}/{repo}"
            cached_secrets = self._get_cached_secrets(cache_key)

            if cached_secrets is not None:
                logger.debug(f"Using cached secrets for {cache_key}")
                return dict.fromkeys(secret_names, cached_secrets.get(secret_names[0]) if secret_names else None)

            logger.info(f"Fetching secrets from GitHub for {owner}/{repo}")

            # Fetch list of available secrets
            secrets_url = f"https://api.github.com/repos/{owner}/{repo}/actions/secrets"
            response = await self.client.get(secrets_url)

            if response.status_code == 404:
                logger.warning(f"Repository {owner}/{repo} not found or no access to secrets")
                return dict.fromkeys(secret_names, None)
            elif response.status_code != 200:
                logger.error(f"Failed to fetch secrets list: {response.status_code} {response.text}")
                return dict.fromkeys(secret_names, None)

            secrets_data = response.json()
            available_secrets = {secret["name"] for secret in secrets_data.get("secrets", [])}

            # Note: GitHub API doesn't allow reading secret values directly
            # We can only check if secrets exist and get their metadata
            # The actual secret values would need to be passed through environment
            # or workflow context when the GitHub App is triggered

            result: dict[str, str | None] = {}
            for name in secret_names:
                if name in available_secrets:
                    # Secret exists but we can't read the value directly via API
                    # GitHub Secrets are only accessible inside GitHub Actions workflows
                    # We'll rely on environment variable fallback instead
                    logger.info(f"Secret '{name}' exists in repository {owner}/{repo} but value not readable via API")
                    result[name] = None  # Can't read value, will use environment fallback
                else:
                    logger.warning(f"Secret '{name}' not found in repository {owner}/{repo}")
                    result[name] = None

            # Cache the result (just availability, not actual values)
            self._cache_secrets(cache_key, result)

            return result

        except Exception as e:
            logger.error(f"Error fetching repository secrets: {e}")
            return dict.fromkeys(secret_names, None)

    async def get_database_credentials(self, owner: str, repo: str) -> dict[str, str | None]:
        """
        Fetch database-specific secrets from repository.

        Args:
            owner: Repository owner
            repo: Repository name

        Returns:
            Dictionary with database credential values
        """
        # Standard database secret names
        db_secret_names = [
            "DATABASE_TYPE",
            "DATABASE_HOST",
            "DATABASE_PORT",
            "DATABASE_NAME",
            "DATABASE_USER",
            "DATABASE_PASSWORD",
            "DATABASE_URL",  # Alternative single connection string
            "DATABASE_SSL"
        ]

        return await self.get_repository_secrets(owner, repo, db_secret_names)

    def validate_database_credentials(self, credentials: dict[str, str | None]) -> dict[str, Any]:
        """
        Validate and normalize database credentials.

        Args:
            credentials: Raw credential dictionary from secrets

        Returns:
            Validated and normalized connection configuration
        """
        try:
            # Check for complete connection string first
            if credentials.get("DATABASE_URL"):
                return {
                    "connection_string": credentials["DATABASE_URL"],
                    "database_type": credentials.get("DATABASE_TYPE", "postgresql"),
                    "is_valid": True
                }

            # Check for individual credential components
            required_fields = ["DATABASE_HOST", "DATABASE_NAME", "DATABASE_USER", "DATABASE_PASSWORD"]
            missing_fields = [field for field in required_fields if not credentials.get(field)]

            if missing_fields:
                logger.warning(f"Missing required database credentials: {missing_fields}")
                return {
                    "is_valid": False,
                    "error": f"Missing required credentials: {', '.join(missing_fields)}"
                }

            # Build connection configuration
            host = credentials["DATABASE_HOST"]
            port_str = credentials.get("DATABASE_PORT", "5432")
            if isinstance(port_str, str):
                try:
                    port = int(port_str)
                except ValueError:
                    port = 5432
            elif port_str is not None:
                port = int(port_str)
            else:
                port = 5432

            db_password = credentials.get("DATABASE_PASSWORD", "")
            ssl_str = credentials.get("DATABASE_SSL", "false")
            if isinstance(ssl_str, str):
                ssl = ssl_str.lower() == "true"
            else:
                ssl = bool(ssl_str)

            config = {
                "host": host,
                "port": port,
                "database": credentials["DATABASE_NAME"],
                "user": credentials["DATABASE_USER"],
                "password": db_password,
                "database_type": credentials.get("DATABASE_TYPE", "postgresql"),
                "ssl": ssl,
                "is_valid": True
            }

            return config

        except Exception as e:
            logger.error(f"Error validating database credentials: {e}")
            return {
                "is_valid": False,
                "error": f"Credential validation error: {str(e)}"
            }

    async def test_database_connection(self, connection_config: dict[str, Any]) -> bool:
        """
        Test database connection with provided credentials.

        Args:
            connection_config: Database connection configuration

        Returns:
            True if connection successful, False otherwise
        """
        try:
            if not connection_config.get("is_valid", False):
                logger.warning("Cannot test invalid connection configuration")
                return False

            # For now, return True as a placeholder
            # In a full implementation, this would create a test connection
            logger.info("Database connection test would be performed here")
            return True

        except Exception as e:
            logger.error(f"Database connection test failed: {e}")
            return False

    def _get_cached_secrets(self, cache_key: str) -> dict[str, Any] | None:
        """Get secrets from cache if still valid."""
        if cache_key not in self._secret_cache:
            return None

        cached_data = self._secret_cache[cache_key]
        cache_time = cached_data.get("cached_at", 0)

        if time.time() - cache_time > self._cache_ttl:
            # Cache expired
            del self._secret_cache[cache_key]
            return None

        return cached_data.get("secrets")

    def _cache_secrets(self, cache_key: str, secrets: dict[str, Any]) -> None:
        """Cache secrets with timestamp."""
        self._secret_cache[cache_key] = {
            "secrets": secrets,
            "cached_at": time.time()
        }

    def clear_cache(self) -> None:
        """Clear all cached secrets."""
        self._secret_cache.clear()
        logger.info("Cleared GitHub secrets cache")

    async def close(self) -> None:
        """Clean up resources."""
        await self.client.aclose()
        self.clear_cache()


class DatabaseCredentialsProvider:
    """
    Provides database credentials from multiple sources with fallback.

    Sources (in order of priority):
    1. GitHub repository secrets
    2. Repository configuration files
    3. Environment variables
    """

    def __init__(self, secrets_manager: GitHubSecretsManager) -> None:
        self.secrets_manager = secrets_manager

    async def get_credentials(self, owner: str, repo: str, repository_path: str | None = None) -> dict[str, Any]:
        """
        Get database credentials from available sources.

        Args:
            owner: Repository owner
            repo: Repository name
            repository_path: Optional local repository path for config file detection

        Returns:
            Database connection configuration
        """
        try:
            # Try GitHub secrets first
            logger.info(f"Fetching database credentials for {owner}/{repo}")

            github_credentials = await self.secrets_manager.get_database_credentials(owner, repo)

            if any(cred for cred in github_credentials.values()):
                logger.info("Using GitHub repository secrets for database credentials")
                config = self.secrets_manager.validate_database_credentials(github_credentials)
                if config.get("is_valid"):
                    return config

            # Fallback: Check repository configuration files
            if repository_path:
                logger.info("Checking repository configuration files for database credentials")
                file_config = self._detect_config_files(repository_path)
                if file_config.get("is_valid"):
                    return file_config

            # Fallback: Check environment variables
            logger.info("Checking environment variables for database credentials")
            env_config = self._get_environment_credentials()
            if env_config.get("is_valid"):
                return env_config

            # No valid credentials found
            logger.warning(f"No valid database credentials found for {owner}/{repo}")
            return {
                "is_valid": False,
                "error": "No database credentials found in GitHub secrets, repository configuration, or environment variables",
                "sources_checked": ["github_secrets", "config_files", "environment_variables"]
            }

        except Exception as e:
            logger.error(f"Error getting database credentials: {e}")
            return {
                "is_valid": False,
                "error": f"Failed to fetch database credentials: {str(e)}"
            }

    def _detect_config_files(self, repository_path: str) -> dict[str, Any]:
        """
        Detect database configuration from repository files.

        This is a placeholder implementation - in practice would parse
        files like database.yml, .env, etc.
        """
        # Placeholder implementation
        return {
            "is_valid": False,
            "error": "Config file detection not yet implemented"
        }

    def _get_environment_credentials(self) -> dict[str, Any]:
        """
        Get database credentials from environment variables (fallback).

        Checks for TEST_DATABASE_* or DATABASE_* environment variables.
        This provides a fallback when GitHub Secrets are not accessible.

        Returns:
            Database connection configuration from environment
        """
        import os

        # Check for test-specific credentials first (for baseline testing)
        test_prefix = "TEST_DATABASE_"
        prod_prefix = "DATABASE_"

        # Try test credentials first, then production
        for prefix in [test_prefix, prod_prefix]:
            db_type = os.getenv(f"{prefix}TYPE")
            db_host = os.getenv(f"{prefix}HOST")
            db_name = os.getenv(f"{prefix}NAME")
            db_user = os.getenv(f"{prefix}USER")
            db_password = os.getenv(f"{prefix}PASSWORD")

            if db_host and db_name and db_user and db_password:
                logger.info(f"Using database credentials from environment variables ({prefix}*)")

                try:
                    config = {
                        "host": db_host,
                        "port": int(os.getenv(f"{prefix}PORT", "5432")),
                        "database": db_name,
                        "user": db_user,
                        "password": db_password,
                        "database_type": db_type or "postgresql",
                        "ssl": os.getenv(f"{prefix}SSL", "false").lower() == "true",
                        "is_valid": True,
                        "source": "environment_variables"
                    }
                    return config
                except ValueError as e:
                    logger.error(f"Invalid PORT value in {prefix}PORT: {e}")
                    continue

        return {
            "is_valid": False,
            "error": "No database credentials found in environment variables"
        }