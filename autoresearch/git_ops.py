"""Git helpers for the autoresearch experiment loop."""

from __future__ import annotations

from pathlib import Path

import git
from git import InvalidGitRepositoryError, NoSuchPathError, Repo


class GitOps:
    """Thin wrapper around gitpython for experiment loop operations."""

    def __init__(self, repo_path: str) -> None:
        path = Path(repo_path).resolve()
        try:
            self._repo = Repo(str(path))
        except InvalidGitRepositoryError:
            raise RuntimeError(
                f"'{repo_path}' is not a valid git repository. "
                "Run 'git init' first or provide the correct path."
            ) from None
        except NoSuchPathError:
            raise RuntimeError(
                f"Path '{repo_path}' does not exist."
            ) from None

    # ------------------------------------------------------------------
    # Read-only helpers
    # ------------------------------------------------------------------

    def get_head_sha(self) -> str:
        """Return the current HEAD commit SHA."""
        return self._repo.head.commit.hexsha

    def is_clean(self) -> bool:
        """Return True if the working tree has no uncommitted changes."""
        return not self._repo.is_dirty(untracked_files=True)

    def get_status(self) -> str:
        """Return a human-readable git status string."""
        return self._repo.git.status()

    def get_diff(self, sha: str) -> str:
        """Return the unified diff between *sha* and HEAD.

        Shows what has changed since the given commit.
        """
        return self._repo.git.diff(sha, "HEAD")

    # ------------------------------------------------------------------
    # Mutating helpers
    # ------------------------------------------------------------------

    def commit(self, message: str) -> str:
        """Stage all changes and create a commit.

        Returns the new commit SHA.
        Raises ValueError if there is nothing to commit.
        """
        # Stage all changes (new files, modifications, deletions)
        self._repo.git.add("--all")

        # Check if there is actually anything staged
        if not self._repo.index.diff("HEAD") and not self._repo.untracked_files:
            # Also check against an empty tree when HEAD does not exist yet
            try:
                self._repo.head.commit  # will raise if no commits yet
                staged = self._repo.index.diff("HEAD")
            except ValueError:
                # No commits yet — check if there is anything in the index
                staged = list(self._repo.index.diff(None))
                if not staged:
                    raise ValueError(
                        "Nothing to commit: working tree is clean."
                    )
            else:
                if not staged:
                    raise ValueError(
                        "Nothing to commit: working tree is clean."
                    )

        new_commit = self._repo.index.commit(message)
        return new_commit.hexsha

    def reset_hard(self, sha: str) -> None:
        """Perform a hard reset to the given commit SHA.

        Discards all uncommitted changes and moves HEAD to *sha*.
        """
        self._repo.git.reset("--hard", sha)
