"""
GitHub webhook processing for BadDocs.

Handles GitHub webhook events, signature verification, and automated documentation generation.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .auth import GitHubAppAuth


@dataclass
class WebhookEvent:
    """GitHub webhook event data."""
    event_type: str
    delivery_id: str
    installation_id: int | None
    repository: dict[str, Any]
    sender: dict[str, Any]
    payload: dict[str, Any]
    signature: str | None = None


@dataclass
class RepositoryConfig:
    """Repository-specific configuration."""
    repository_id: str
    target_branch: str = 'docs'
    webhook_enabled: bool = True
    auto_process_pushes: bool = True
    process_on_branches: list[str] = None  # type: ignore
    github_installation_id: int | None = None

    def __post_init__(self) -> None:
        # Ensure process_on_branches is always a list
        if self.process_on_branches is None:
            object.__setattr__(self, 'process_on_branches', ['main', 'master'])


class GitHubWebhookHandler:
    """
    GitHub webhook event handler.

    Processes GitHub webhook events and triggers documentation generation
    for configured repositories and branches.
    """

    def __init__(self, github_auth: GitHubAppAuth, repository_configs: dict[str, RepositoryConfig] | None = None) -> None:
        self.github_auth = github_auth
        self.repository_configs = repository_configs or {}
        self.logger = logging.getLogger(__name__)

    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """
        Verify GitHub webhook signature.

        Args:
            payload: Raw webhook payload
            signature: Signature from X-Hub-Signature-256 header

        Returns:
            True if signature is valid
        """
        return self.github_auth.verify_webhook_signature(payload, signature)

    def parse_webhook_event(self, headers: dict[str, str], payload: dict[str, Any]) -> WebhookEvent:
        """
        Parse GitHub webhook event.

        Args:
            headers: HTTP headers from webhook request
            payload: Webhook payload data

        Returns:
            Parsed webhook event
        """
        event_type = headers.get('X-GitHub-Event', 'unknown')
        delivery_id = headers.get('X-GitHub-Delivery', 'unknown')
        signature = headers.get('X-Hub-Signature-256')

        # Extract common fields
        installation_id: int | None = None
        if 'installation' in payload:
            installation_id = payload['installation'].get('id')

        repository = payload.get('repository', {})
        sender = payload.get('sender', {})

        return WebhookEvent(
            event_type=event_type,
            delivery_id=delivery_id,
            installation_id=installation_id,
            repository=repository,
            sender=sender,
            payload=payload,
            signature=signature
        )

    def should_process_event(self, event: WebhookEvent) -> bool:
        """
        Determine if webhook event should trigger documentation processing.

        Args:
            event: Webhook event data

        Returns:
            True if event should be processed
        """
        try:
            # Only process supported event types
            if event.event_type not in ['push', 'pull_request']:
                self.logger.debug(f"Ignoring unsupported event type: {event.event_type}")
                return False

            # Check if repository is configured
            repo_full_name = event.repository.get('full_name')
            repo_id = str(event.repository.get('id', ''))

            config = self.get_repository_config(repo_id)
            if not config or not config.webhook_enabled:
                self.logger.debug(f"Webhook processing disabled for repository {repo_full_name}")
                return False

            # For push events, check branch
            if event.event_type == 'push':
                ref = event.payload.get('ref', '')
                if ref.startswith('refs/heads/'):
                    branch = ref[11:]  # Remove 'refs/heads/'

                    if branch not in config.process_on_branches:
                        self.logger.debug(f"Ignoring push to branch '{branch}' - not in configured branches {config.process_on_branches}")
                        return False

                    # Skip if this is the docs branch to avoid infinite loops
                    if branch == config.target_branch:
                        self.logger.debug(f"Ignoring push to documentation branch '{branch}'")
                        return False

            # For pull request events, only process opened/synchronized
            elif event.event_type == 'pull_request':
                action = event.payload.get('action')
                if action not in ['opened', 'synchronize']:
                    self.logger.debug(f"Ignoring pull request action: {action}")
                    return False

                # Check if PR targets a configured branch
                pr_base_ref = event.payload.get('pull_request', {}).get('base', {}).get('ref')
                if pr_base_ref not in config.process_on_branches:
                    self.logger.debug(f"Ignoring PR targeting branch '{pr_base_ref}' - not in configured branches")
                    return False

            return True

        except Exception as e:
            self.logger.error(f"Error checking if event should be processed: {e}")
            return False

    def get_changed_files(self, event: WebhookEvent) -> list[str]:
        """
        Extract list of changed files from webhook event.

        Args:
            event: Webhook event data

        Returns:
            List of changed file paths
        """
        changed_files = []

        try:
            if event.event_type == 'push':
                # Get changed files from commits
                commits = event.payload.get('commits', [])
                for commit in commits:
                    changed_files.extend(commit.get('added', []))
                    changed_files.extend(commit.get('modified', []))
                    # Note: We might want to handle removed files differently

            elif event.event_type == 'pull_request':
                # For PR events, we'd need to make an API call to get changed files
                # This is a simplified version - in production you'd fetch the actual changes
                pr_data = event.payload.get('pull_request', {})
                head_sha = pr_data.get('head', {}).get('sha')
                base_sha = pr_data.get('base', {}).get('sha')

                if head_sha and base_sha and event.installation_id:
                    # In a full implementation, you'd make GitHub API calls to get the diff
                    self.logger.info(f"PR event detected - would fetch changes between {base_sha} and {head_sha}")

            # Remove duplicates and return
            return list(set(changed_files))

        except Exception as e:
            self.logger.error(f"Error extracting changed files: {e}")
            return []

    def get_repository_config(self, repository_id: str) -> RepositoryConfig | None:
        """
        Get repository configuration.

        Args:
            repository_id: Repository ID

        Returns:
            Repository configuration or None
        """
        return self.repository_configs.get(repository_id)

    def set_repository_config(self, repository_id: str, config: RepositoryConfig) -> None:
        """
        Set repository configuration.

        Args:
            repository_id: Repository ID
            config: Repository configuration
        """
        self.repository_configs[repository_id] = config

    async def process_webhook_event(self, event: WebhookEvent) -> dict[str, object]:
        """
        Process webhook event and trigger documentation generation.

        Args:
            event: Webhook event data

        Returns:
            Processing result
        """
        try:
            self.logger.info(f"Processing webhook event: {event.event_type} for {event.repository.get('full_name')}")

            # Verify event should be processed
            if not self.should_process_event(event):
                return {
                    'status': 'ignored',
                    'reason': 'Event does not meet processing criteria'
                }

            # Get repository information
            repo_data = event.repository
            repo_full_name = repo_data.get('full_name')
            repo_id = str(repo_data.get('id', ''))
            repo_url = repo_data.get('clone_url')
            _ = repo_data.get('default_branch', 'main')  # Not used currently

            # Get repository configuration
            config = self.get_repository_config(repo_id)
            if not config:
                # Create default configuration
                config = RepositoryConfig(
                    repository_id=repo_id,
                    process_on_branches=['main', 'master']
                )
                self.set_repository_config(repo_id, config)

            # Get changed files for incremental processing
            changed_files = self.get_changed_files(event)

            # Determine target branch and commit info
            target_branch = config.target_branch
            commit_sha: str | None = None
            commit_message = f"Update documentation for {repo_full_name}"

            if event.event_type == 'push':
                commit_sha = event.payload.get('after')
                if event.payload.get('commits'):
                    latest_commit = event.payload['commits'][-1]
                    commit_message = f"Update documentation - {latest_commit.get('message', '')[:50]}"

            elif event.event_type == 'pull_request':
                pr_data = event.payload.get('pull_request', {})
                commit_sha = pr_data.get('head', {}).get('sha')
                pr_number = pr_data.get('number')
                pr_title = pr_data.get('title', '')
                commit_message = f"Update documentation for PR #{pr_number}: {pr_title}"

            # Prepare workflow parameters for documentation generation
            workflow_params = {
                'repository_url': repo_url,
                'repository_id': repo_id,
                'repository_name': repo_full_name,
                'target_branch': target_branch,
                'commit_sha': commit_sha,
                'commit_message': commit_message,
                'github_installation_id': event.installation_id,
                'incremental': bool(changed_files),
                'changed_files': changed_files,
                'webhook_event': {
                    'type': event.event_type,
                    'delivery_id': event.delivery_id,
                    'timestamp': datetime.utcnow().isoformat()
                }
            }

            self.logger.info(f"Triggering documentation workflow for {repo_full_name} (installation: {event.installation_id})")

            # Return workflow parameters for external processing
            # In a full implementation, this would trigger the actual workflow
            return {
                'status': 'processed',
                'repository': repo_full_name,
                'event_type': event.event_type,
                'changed_files': len(changed_files),
                'workflow_params': workflow_params,
                'config': {
                    'target_branch': config.target_branch,
                    'auto_process': config.auto_process_pushes
                }
            }

        except Exception as e:
            self.logger.error(f"Error processing webhook event: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'event_type': event.event_type,
                'repository': event.repository.get('full_name', 'unknown')
            }

    def create_status_check(self, event: WebhookEvent, state: str, description: str, target_url: str | None = None) -> bool:
        """
        Create GitHub commit status check.

        Args:
            event: Webhook event data
            state: Status state (pending, success, failure, error)
            description: Status description
            target_url: Optional URL to link to

        Returns:
            True if status was created successfully
        """
        try:
            if not event.installation_id:
                self.logger.warning("No installation ID - cannot create status check")
                return False

            repo_data = event.repository
            owner = repo_data.get('owner', {}).get('login')
            repo_name = repo_data.get('name')

            # Get commit SHA
            commit_sha: str | None = None
            if event.event_type == 'push':
                commit_sha = event.payload.get('after')
            elif event.event_type == 'pull_request':
                commit_sha = event.payload.get('pull_request', {}).get('head', {}).get('sha')

            if not commit_sha or not owner or not repo_name:
                self.logger.warning("Missing required data for status check")
                return False

            # Get installation token
            access_token = self.github_auth.get_installation_token(event.installation_id)

            import requests

            headers = {
                'Authorization': f'token {access_token}',
                'Accept': 'application/vnd.github.v3+json',
                'User-Agent': 'BadDocs-GitHub-App'
            }

            status_data = {
                'state': state,
                'description': description,
                'context': 'baddocs/documentation'
            }

            if target_url:
                status_data['target_url'] = target_url

            url = f'https://api.github.com/repos/{owner}/{repo_name}/statuses/{commit_sha}'
            response = requests.post(url, headers=headers, json=status_data)

            if response.status_code == 201:
                self.logger.info(f"Created status check for {owner}/{repo_name}@{commit_sha[:8]}: {state}")
                return True
            else:
                self.logger.error(f"Failed to create status check: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            self.logger.error(f"Error creating status check: {e}")
            return False