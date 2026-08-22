# hot git

## Purpose

`hot-git` is a server-oriented Python library for fast Git repository access without a working-tree checkout. The first goal is to turn the benchmarked ideas into a small, correct library that can later be used by `personal-repo-mcp` and potentially other agent systems.

The library should treat Git's object database and refs as the source of truth. It should not introduce a second database or cache whose state must be reconciled with Git.

## Design principles

- **Treeless first:** all library mutations operate directly on Git objects and refs; no working tree is required.
- **Git remains authoritative:** hot-git accelerates access to Git rather than replacing Git's storage semantics.
- **Per-repository workers:** a repository gets one lazily-created worker shared by callers. Workers are not created per request or per agent.
- **Persistent where it helps:** keep long-lived Git protocols such as `cat-file --batch` alive; don't create persistent subprocesses merely for architectural symmetry.
- **CAS for refs:** use Git's ref update semantics and expected-old values rather than implementing our own locking protocol.
- **Correctness before speed:** every generated object must be valid to ordinary Git, and failed concurrent updates must not silently overwrite another writer.
- **Explicit scope:** the initial implementation supports normal SHA-1 repositories. SHA-256 support is a later milestone unless the implementation can be added without compromising the initial correctness boundary.

## Architecture

```text
Caller
  |
  v
Repository
  |
  +-- ObjectReader       persistent cat-file --batch
  |
  +-- ObjectStore        blob/tree/commit objects
  |
  +-- TreeBuilder        treeless tree construction
  |
  +-- CommitBuilder      commit construction
  |
  +-- RefStore           CAS ref updates
  |
  +-- RepositoryWorker   lifecycle + shared access
```

A `RepositoryWorker` owns resources associated with exactly one repository. It is started lazily on first use and can eventually be evicted after an idle timeout. The initial implementation should keep lifecycle management simple and deterministic.
