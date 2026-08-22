"""Fast, treeless Git repository access."""

from .commits import CommitBuilder, CommitIdentity
from .edit import Change, EditResult, Editor
from .objects import ObjectStore
from .refs import RefConflictError, RefStore
from .repository import ObjectNotFoundError, Repository, RepositoryError
from .trees import TreeBuilder, TreeEntry
from .worker import RepositoryWorker, WorkerPool

__all__ = [
    "Change",
    "CommitBuilder",
    "CommitIdentity",
    "EditResult",
    "Editor",
    "ObjectNotFoundError",
    "ObjectStore",
    "RefConflictError",
    "RefStore",
    "Repository",
    "RepositoryError",
    "RepositoryWorker",
    "TreeBuilder",
    "TreeEntry",
    "WorkerPool",
]
