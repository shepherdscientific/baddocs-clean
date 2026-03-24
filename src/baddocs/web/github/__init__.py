"""
GitHub integration module for BadDocs.

Provides GitHub App authentication, webhook processing, repository management, and PR automation.
"""

from .auth import GitHubAppAuth, GitHubAuth
from .pr_manager import GitHubPRManager
from .webhooks import GitHubWebhookHandler

__all__ = [
    'GitHubAppAuth',
    'GitHubAuth',
    'GitHubPRManager',
    'GitHubWebhookHandler',
]