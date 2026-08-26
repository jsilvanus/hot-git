"""Fast, treeless Git repository access."""

from .commits import CommitBuilder, CommitIdentity
from .edit import Change, EditResult, Editor
from .history import Commit, History, Identity, Ref
from .objects import ObjectStore
from .refs import RefConflictError, RefStore
from .remote import RemoteFetchError, RemoteRepository
from .repository import ObjectNotFoundError, Repository, RepositoryError
from .trees import TreeBuilder, TreeEntry
from .worker import RepositoryWorker, WorkerPool

__all__ = [
    "Change",
    "Commit",
    "CommitBuilder",
    "CommitIdentity",
    "EditResult",
    "Editor",
    "History",
    "Identity",
    "ObjectNotFoundError",
    "ObjectStore",
    "Ref",
    "RefConflictError",
    "RefStore",
    "RemoteFetchError",
    "RemoteRepository",
    "Repository",
    "RepositoryError",
    "RepositoryWorker",
    "TreeBuilder",
    "TreeEntry",
    "WorkerPool",
]
