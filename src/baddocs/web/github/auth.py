"""
GitHub App authentication for BadDocs.

Handles JWT token generation, installation token management, and GitHub API authentication.
"""

import hashlib
import hmac
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
import requests


@dataclass
class GitHubInstallation:
    """GitHub App installation information."""
    installation_id: int
    repository_ids: list[str]
    access_token: str | None = None
    token_expires_at: datetime | None = None


class GitHubAppAuth:
    """
    GitHub App authentication manager.

    Handles JWT token generation for GitHub App authentication
    and manages installation access tokens for repository access.
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

        # GitHub App configuration from environment
        self.app_id = os.getenv('GITHUB_APP_ID')
        self.private_key_path = os.getenv('GITHUB_APP_PRIVATE_KEY_PATH')
        self.private_key_content = os.getenv('GITHUB_APP_PRIVATE_KEY')
        self.webhook_secret = os.getenv('GITHUB_WEBHOOK_SECRET')

        # Cache for installation tokens
        self._installation_cache: dict[int, GitHubInstallation] = {}

        # Validate configuration
        self._validate_config()

    def _validate_config(self) -> None:
        """Validate GitHub App configuration."""
        if not self.app_id:
            raise ValueError("GITHUB_APP_ID environment variable is required")

        if not self.private_key_path and not self.private_key_content:
            raise ValueError("Either GITHUB_APP_PRIVATE_KEY_PATH or GITHUB_APP_PRIVATE_KEY environment variable is required")

        if not self.webhook_secret:
            self.logger.warning("GITHUB_WEBHOOK_SECRET not set - webhook signature verification will be disabled")

    def _get_private_key(self) -> str:
        """Get the private key content."""
        if self.private_key_content:
            return self.private_key_content

        if self.private_key_path and os.path.exists(self.private_key_path):
            with open(self.private_key_path) as f:
                return f.read()

        raise ValueError("GitHub App private key not found")

    def generate_jwt_token(self, expiration_minutes: int = 10) -> str:
        """
        Generate JWT token for GitHub App authentication.

        Args:
            expiration_minutes: Token expiration time in minutes (max 10)

        Returns:
            JWT token string
        """
        try:
            # GitHub requires expiration to be no more than 10 minutes
            expiration_minutes = min(expiration_minutes, 10)

            now = int(time.time())
            payload = {
                'iat': now,  # Issued at time
                'exp': now + (expiration_minutes * 60),  # Expiration time
                'iss': self.app_id  # Issuer (GitHub App ID)
            }

            private_key = self._get_private_key()

            # Generate JWT token
            token = jwt.encode(payload, private_key, algorithm='RS256')

            self.logger.debug(f"Generated JWT token for GitHub App {self.app_id}")
            return token

        except Exception as e:
            self.logger.error(f"Failed to generate JWT token: {e}")
            raise

    def get_installation_token(self, installation_id: int, repository_ids: list[str] | None = None) -> str:
        """
        Get installation access token for repository access.

        Args:
            installation_id: GitHub App installation ID
            repository_ids: Optional list of repository IDs to limit access

        Returns:
            Installation access token
        """
        try:
            # Check cache for valid token
            if installation_id in self._installation_cache:
                installation = self._installation_cache[installation_id]
                if (installation.access_token and
                    installation.token_expires_at and
                    installation.token_expires_at > datetime.now(timezone.utc) + timedelta(minutes=5)):
                    return installation.access_token

            # Generate new installation token
            jwt_token = self.generate_jwt_token()

            headers = {
                'Authorization': f'Bearer {jwt_token}',
                'Accept': 'application/vnd.github.v3+json',
                'User-Agent': 'BadDocs-GitHub-App'
            }

            # Prepare request data
            data: dict[str, object] = {}
            if repository_ids:
                data['repository_ids'] = repository_ids

            # Request installation access token
            url = f'https://api.github.com/app/installations/{installation_id}/access_tokens'
            response = requests.post(url, headers=headers, json=data if data else None)

            if response.status_code != 201:
                self.logger.error(f"Failed to get installation token: {response.status_code} - {response.text}")
                response.raise_for_status()

            token_data = response.json()
            access_token = token_data['token']
            expires_at = datetime.fromisoformat(token_data['expires_at'].replace('Z', '+00:00'))

            # Cache the installation token
            installation = GitHubInstallation(
                installation_id=installation_id,
                repository_ids=repository_ids or [],
                access_token=access_token,
                token_expires_at=expires_at
            )
            self._installation_cache[installation_id] = installation

            self.logger.info(f"Successfully obtained installation token for installation {installation_id}")
            return access_token

        except Exception as e:
            self.logger.error(f"Failed to get installation token for {installation_id}: {e}")
            raise

    def get_app_installations(self) -> list[dict[str, object]]:
        """
        Get list of installations for the GitHub App.

        Returns:
            List of installation data
        """
        try:
            jwt_token = self.generate_jwt_token()

            headers = {
                'Authorization': f'Bearer {jwt_token}',
                'Accept': 'application/vnd.github.v3+json',
                'User-Agent': 'BadDocs-GitHub-App'
            }

            url = 'https://api.github.com/app/installations'
            response = requests.get(url, headers=headers)

            if response.status_code != 200:
                self.logger.error(f"Failed to get installations: {response.status_code} - {response.text}")
                response.raise_for_status()

            installations = response.json()
            self.logger.info(f"Found {len(installations)} GitHub App installations")
            return installations

        except Exception as e:
            self.logger.error(f"Failed to get app installations: {e}")
            raise

    def get_installation_repositories(self, installation_id: int) -> list[dict[str, object]]:
        """
        Get list of repositories accessible by an installation.

        Args:
            installation_id: GitHub App installation ID

        Returns:
            List of repository data
        """
        try:
            access_token = self.get_installation_token(installation_id)

            headers = {
                'Authorization': f'token {access_token}',
                'Accept': 'application/vnd.github.v3+json',
                'User-Agent': 'BadDocs-GitHub-App'
            }

            url = 'https://api.github.com/installation/repositories'
            response = requests.get(url, headers=headers)

            if response.status_code != 200:
                self.logger.error(f"Failed to get installation repositories: {response.status_code} - {response.text}")
                response.raise_for_status()

            repos_data = response.json()
            repositories = repos_data.get('repositories', [])

            self.logger.info(f"Found {len(repositories)} repositories for installation {installation_id}")
            return repositories

        except Exception as e:
            self.logger.error(f"Failed to get installation repositories for {installation_id}: {e}")
            raise

    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """
        Verify GitHub webhook signature.

        Args:
            payload: Raw webhook payload
            signature: Signature from X-Hub-Signature-256 header

        Returns:
            True if signature is valid, False otherwise
        """
        if not self.webhook_secret:
            self.logger.warning("Webhook secret not configured - skipping signature verification")
            return True

        try:
            # Remove 'sha256=' prefix from signature
            if signature.startswith('sha256='):
                signature = signature[7:]

            # Compute expected signature
            expected_signature = hmac.new(
                self.webhook_secret.encode('utf-8'),
                payload,
                hashlib.sha256
            ).hexdigest()

            # Compare signatures
            return hmac.compare_digest(expected_signature, signature)

        except Exception as e:
            self.logger.error(f"Failed to verify webhook signature: {e}")
            return False

    def get_repository_content(self, installation_id: int, owner: str, repo: str, path: str = "", ref: str = "main") -> dict[str, object]:
        """
        Get repository content using GitHub App authentication.

        Args:
            installation_id: GitHub App installation ID
            owner: Repository owner
            repo: Repository name
            path: Path to content (empty for root)
            ref: Git reference (branch/tag/commit)

        Returns:
            Repository content data
        """
        try:
            access_token = self.get_installation_token(installation_id)

            headers = {
                'Authorization': f'token {access_token}',
                'Accept': 'application/vnd.github.v3+json',
                'User-Agent': 'BadDocs-GitHub-App'
            }

            url = f'https://api.github.com/repos/{owner}/{repo}/contents/{path}'
            params: dict[str, str] = {}
            if ref:
                params['ref'] = ref

            response = requests.get(url, headers=headers, params=params)

            if response.status_code != 200:
                self.logger.error(f"Failed to get repository content: {response.status_code} - {response.text}")
                response.raise_for_status()

            return response.json()

        except Exception as e:
            self.logger.error(f"Failed to get repository content for {owner}/{repo}: {e}")
            raise

    def is_configured(self) -> bool:
        """Check if GitHub App authentication is properly configured."""
        try:
            return bool(self.app_id and (self.private_key_path or self.private_key_content))
        except Exception:
            return False


class GitHubAuth:
    """
    Legacy GitHub authentication (for backward compatibility).

    Handles personal access token authentication.
    """

    def __init__(self, token: str | None = None) -> None:
        self.token = token or os.getenv('GITHUB_TOKEN')
        self.logger = logging.getLogger(__name__)

    def get_headers(self) -> dict[str, str]:
        """Get authentication headers."""
        if not self.token:
            return {}

        return {
            'Authorization': f'token {self.token}',
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'BadDocs-GitHub-Client'
        }

    def is_configured(self) -> bool:
        """Check if GitHub authentication is configured."""
        return bool(self.token)