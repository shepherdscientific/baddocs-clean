"""
Run-state persistence for BadDocs incremental processing.

Remembers the git commit SHA that docs were last generated from, keyed by
repository root, so the next run can diff against it instead of re-reading the
whole tree.

Staleness in this module is keyed on git commit/blob identity, never on file
mtimes: a fresh checkout (e.g. a CI runner) resets mtimes to the checkout time,
which would make every file look "modified" and defeat incremental generation.
"""

import sqlite3
import subprocess
from pathlib import Path
from typing import Optional, Union
import logging

from ..core.exceptions import ProcessingError

PathLike = Union[str, Path]


class RunState:
    """
    Persists the last-run commit SHA per repository.

    The store lives next to the change-tracking database under ``storage_path``
    (its own ``run_state.db``). Callers MUST only call :meth:`save_run_sha`
    after a generation run completes successfully; a crashed or partial run
    leaves the previous SHA intact so the next run still diffs from a known-good
    base.
    """

    def __init__(self, storage_path: Path) -> None:
        """
        Initialize the run-state store.

        Args:
            storage_path: Directory holding the incremental databases (the same
                ``storage_path`` used by the change-tracking DB).
        """
        self.storage_path = Path(storage_path)
        self.db_path = self.storage_path / 'run_state.db'
        self.logger = logging.getLogger(__name__)

        # Ensure storage directory exists
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self._init_database()

    def _init_database(self) -> None:
        """Initialize the run-state database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS run_state (
                        repo_root TEXT PRIMARY KEY,
                        last_run_sha TEXT NOT NULL,
                        updated_at REAL NOT NULL DEFAULT (julianday('now'))
                    )
                ''')
                conn.commit()
        except sqlite3.Error as e:
            raise ProcessingError(f"Failed to initialize run-state database: {e}") from e

    @staticmethod
    def _repo_key(repo: PathLike) -> str:
        """Normalize a repo path to a stable, absolute key."""
        return str(Path(repo).resolve())

    def save_run_sha(self, repo: PathLike, sha: str) -> None:
        """
        Record the commit SHA that docs were last generated from.

        Call this ONLY after a generation run completes successfully.

        Args:
            repo: Repository root (used as the key).
            sha: The commit SHA generated from (typically HEAD at run start).
        """
        if not sha:
            raise ProcessingError("Cannot save an empty run SHA")

        repo_key = self._repo_key(repo)
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    INSERT INTO run_state (repo_root, last_run_sha, updated_at)
                    VALUES (?, ?, julianday('now'))
                    ON CONFLICT(repo_root) DO UPDATE SET
                        last_run_sha = excluded.last_run_sha,
                        updated_at = excluded.updated_at
                    ''',
                    (repo_key, sha),
                )
                conn.commit()
        except sqlite3.Error as e:
            raise ProcessingError(f"Failed to save run SHA: {e}") from e

    def get_run_sha(self, repo: PathLike) -> Optional[str]:
        """
        Return the last-run commit SHA for a repo, or None if never run.

        Args:
            repo: Repository root (used as the key).

        Returns:
            The persisted SHA, or None if no successful run is recorded.
        """
        repo_key = self._repo_key(repo)
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT last_run_sha FROM run_state WHERE repo_root = ?',
                    (repo_key,),
                )
                row = cursor.fetchone()
                return row[0] if row else None
        except sqlite3.Error as e:
            raise ProcessingError(f"Failed to read run SHA: {e}") from e

    def get_current_sha(self, repo: PathLike) -> str:
        """
        Return the current HEAD commit SHA via ``git rev-parse HEAD``.

        Deliberately uses git's commit identity rather than any file mtime so a
        fresh checkout does not look like a full change set.

        Args:
            repo: Repository root.

        Returns:
            The current HEAD commit SHA.
        """
        try:
            result = subprocess.run(
                ['git', 'rev-parse', 'HEAD'],
                cwd=str(Path(repo)),
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            raise ProcessingError(f"Failed to read current HEAD SHA: {e.stderr}") from e
        except Exception as e:
            raise ProcessingError(f"Failed to run git rev-parse: {e}") from e
