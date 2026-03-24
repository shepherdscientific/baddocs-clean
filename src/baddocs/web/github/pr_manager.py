"""
GitHub Pull Request management for BadDocs.

Handles automated pull request creation, management, and merging for documentation updates.
"""

import logging
from dataclasses import dataclass

from .auth import GitHubAppAuth


@dataclass
class PullRequestData:
    """Pull request creation data."""
    title: str
    body: str
    head: str  # Source branch
    base: str  # Target branch
    draft: bool = False
    maintainer_can_modify: bool = True


@dataclass
class PullRequestResult:
    """Result of pull request operations."""
    success: bool
    pr_number: int | None = None
    pr_url: str | None = None
    error: str | None = None


class GitHubPRManager:
    """
    GitHub Pull Request manager for BadDocs.

    Handles automated PR creation, management, and merging for documentation workflows.
    """

    def __init__(self, github_auth: GitHubAppAuth) -> None:
        self.github_auth = github_auth
        self.logger = logging.getLogger(__name__)

    async def create_documentation_pr(self, installation_id: int, owner: str, repo: str,
                                    source_branch: str, target_branch: str,
                                    pr_template: str | None = None,
                                    extra_tasks: list[str] | None = None,
                                    reviewers: list[str] | None = None) -> PullRequestResult:
        """
        Create a pull request for documentation updates.

        Args:
            installation_id: GitHub App installation ID
            owner: Repository owner
            repo: Repository name
            source_branch: Source branch with documentation changes
            target_branch: Target branch to merge into
            pr_template: Optional PR description template
            extra_tasks: List of extra tasks that were performed
            reviewers: List of GitHub usernames to request reviews from

        Returns:
            PullRequestResult with success status and PR details
        """
        try:
            # Generate PR title and body
            pr_title = f"📚 Update documentation from {source_branch}"
            pr_body = self._generate_pr_body(source_branch, target_branch, extra_tasks, pr_template)

            # Create PR data
            pr_data = PullRequestData(
                title=pr_title,
                body=pr_body,
                head=source_branch,
                base=target_branch,
                draft=False
            )

            # Create the pull request
            result = await self._create_pr(installation_id, owner, repo, pr_data)

            if result.success and result.pr_number and reviewers:
                # Request reviews
                await self._request_reviews(installation_id, owner, repo, result.pr_number, reviewers)

            return result

        except Exception as e:
            self.logger.error(f"Failed to create documentation PR: {e}")
            return PullRequestResult(success=False, error=str(e))

    async def _create_pr(self, installation_id: int, owner: str, repo: str,
                        pr_data: PullRequestData) -> PullRequestResult:
        """Create a pull request via GitHub API."""
        try:
            access_token = self.github_auth.get_installation_token(installation_id)

            import requests

            headers = {
                'Authorization': f'token {access_token}',
                'Accept': 'application/vnd.github.v3+json',
                'User-Agent': 'BadDocs-GitHub-App'
            }

            payload = {
                'title': pr_data.title,
                'body': pr_data.body,
                'head': pr_data.head,
                'base': pr_data.base,
                'draft': pr_data.draft,
                'maintainer_can_modify': pr_data.maintainer_can_modify
            }

            url = f'https://api.github.com/repos/{owner}/{repo}/pulls'
            response = requests.post(url, headers=headers, json=payload)

            if response.status_code == 201:
                pr_info = response.json()
                self.logger.info(f"Created PR #{pr_info['number']}: {pr_info['title']}")

                return PullRequestResult(
                    success=True,
                    pr_number=pr_info['number'],
                    pr_url=pr_info['html_url']
                )
            else:
                error_msg = f"Failed to create PR: {response.status_code} - {response.text}"
                self.logger.error(error_msg)
                return PullRequestResult(success=False, error=error_msg)

        except Exception as e:
            self.logger.error(f"Error creating PR: {e}")
            return PullRequestResult(success=False, error=str(e))

    async def _request_reviews(self, installation_id: int, owner: str, repo: str,
                             pr_number: int, reviewers: list[str]) -> bool:
        """Request reviews from specified users."""
        try:
            access_token = self.github_auth.get_installation_token(installation_id)

            import requests

            headers = {
                'Authorization': f'token {access_token}',
                'Accept': 'application/vnd.github.v3+json',
                'User-Agent': 'BadDocs-GitHub-App'
            }

            payload = {
                'reviewers': reviewers
            }

            url = f'https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/requested_reviewers'
            response = requests.post(url, headers=headers, json=payload)

            if response.status_code == 201:
                self.logger.info(f"Requested reviews from {reviewers} for PR #{pr_number}")
                return True
            else:
                self.logger.warning(f"Failed to request reviews: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            self.logger.error(f"Error requesting reviews: {e}")
            return False

    def _generate_pr_body(self, source_branch: str, target_branch: str,
                         extra_tasks: list[str] | None = None, template: str | None = None) -> str:
        """Generate pull request body with documentation changes summary."""
        if template:
            # Use custom template if provided
            body = template.format(
                source_branch=source_branch,
                target_branch=target_branch,
                extra_tasks=', '.join(extra_tasks or [])
            )
        else:
            # Generate default PR body
            body = f"""## Documentation Update

This PR contains automated documentation updates from the `{source_branch}` branch.

### Changes Made
- 📚 Generated/updated documentation files
- 🔗 Updated cross-references and dependency links
- ✅ Validated documentation structure

"""

            if extra_tasks:
                body += "### Additional Tasks Completed\n"
                task_descriptions = {
                    'security_scan': '🔒 Security scan - checked for exposed secrets',
                    'link_validation': '🔗 Link validation - verified all links work',
                    'version_tagging': '🏷️ Version tagging - tagged with release version',
                    'changelog_update': '📝 Changelog update - updated CHANGELOG.md',
                    'draft_mode': '📝 Draft mode - generated preview documentation',
                    'api_docs_generation': '📋 API docs generation - generated API documentation',
                    'diagram_generation': '📊 Diagram generation - created/updated diagrams',
                    'metrics_collection': '📈 Metrics collection - gathered documentation metrics'
                }

                for task in extra_tasks:
                    description = task_descriptions.get(task, f"✅ {task.replace('_', ' ').title()}")
                    body += f"- {description}\n"

                body += "\n"

            body += """### Review Checklist
- [ ] Documentation is accurate and up-to-date
- [ ] All links and references work correctly
- [ ] Formatting and structure look good
- [ ] No sensitive information is exposed

---
*This PR was automatically created by BadDocs 🤖*
"""

        return body

    async def get_pr_status(self, installation_id: int, owner: str, repo: str,
                          pr_number: int) -> dict[str, object]:
        """Get status of a pull request."""
        try:
            access_token = self.github_auth.get_installation_token(installation_id)

            import requests

            headers = {
                'Authorization': f'token {access_token}',
                'Accept': 'application/vnd.github.v3+json',
                'User-Agent': 'BadDocs-GitHub-App'
            }

            url = f'https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}'
            response = requests.get(url, headers=headers)

            if response.status_code == 200:
                pr_data = response.json()
                return {
                    'number': pr_data['number'],
                    'title': pr_data['title'],
                    'state': pr_data['state'],
                    'merged': pr_data['merged'],
                    'mergeable': pr_data['mergeable'],
                    'url': pr_data['html_url'],
                    'created_at': pr_data['created_at'],
                    'updated_at': pr_data['updated_at']
                }
            else:
                return {'error': f"Failed to get PR status: {response.status_code}"}

        except Exception as e:
            self.logger.error(f"Error getting PR status: {e}")
            return {'error': str(e)}

    async def merge_pr(self, installation_id: int, owner: str, repo: str,
                      pr_number: int, merge_method: str = 'merge') -> bool:
        """
        Merge a pull request (if auto-merge is enabled and conditions are met).

        Args:
            installation_id: GitHub App installation ID
            owner: Repository owner
            repo: Repository name
            pr_number: PR number to merge
            merge_method: Merge method ('merge', 'squash', 'rebase')

        Returns:
            True if merge successful, False otherwise
        """
        try:
            access_token = self.github_auth.get_installation_token(installation_id)

            import requests

            headers = {
                'Authorization': f'token {access_token}',
                'Accept': 'application/vnd.github.v3+json',
                'User-Agent': 'BadDocs-GitHub-App'
            }

            payload = {
                'commit_title': f'Merge documentation update PR #{pr_number}',
                'commit_message': 'Automated documentation update via BadDocs',
                'merge_method': merge_method
            }

            url = f'https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/merge'
            response = requests.put(url, headers=headers, json=payload)

            if response.status_code == 200:
                merge_data = response.json()
                self.logger.info(f"Successfully merged PR #{pr_number}: {merge_data['message']}")
                return True
            else:
                error_msg = f"Failed to merge PR: {response.status_code} - {response.text}"
                self.logger.warning(error_msg)
                return False

        except Exception as e:
            self.logger.error(f"Error merging PR: {e}")
            return False

    async def check_pr_mergeable(self, installation_id: int, owner: str, repo: str,
                                pr_number: int) -> bool:
        """Check if a PR is ready to be merged."""
        try:
            pr_status = await self.get_pr_status(installation_id, owner, repo, pr_number)

            if 'error' in pr_status:
                return False

            # Check if PR is mergeable
            return (
                pr_status.get('state') == 'open' and
                pr_status.get('mergeable') is True and
                not pr_status.get('merged', False)
            )

        except Exception as e:
            self.logger.error(f"Error checking PR mergeable status: {e}")
            return False