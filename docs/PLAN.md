# hot-git implementation plan

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

## Phase 1 — foundation and read path

1. Create the Python package and basic public API.
2. Add a `Repository` abstraction that validates the Git repository and discovers its object format.
3. Implement a persistent `cat-file --batch` reader.
4. Support reading blobs, trees, commits, and arbitrary object IDs through a small typed result API.
5. Make the reader safe for multiple callers through a serialized request path; do not assume multiple simultaneous writes to one stdin are safe.
6. Add startup and shutdown handling, including subprocess failure detection and restart behavior where appropriate.
7. Add tests comparing hot-git results with ordinary Git commands.

**Phase 1 exit criterion:** repeated object reads through hot-git are correct, stable, and materially faster than spawning one Git process per object.

## Phase 2 — treeless object writes

1. Implement blob creation using Git-compatible object hashing and storage.
2. Implement tree construction from existing entries.
3. Implement commit creation with explicit parent, author/committer, and message data.
4. Keep all mutations independent of a working tree.
5. Use safe temporary-file + atomic-rename behavior for loose-object writes.
6. Verify generated objects with ordinary Git commands.
7. Add tests for empty trees, file replacement/addition, nested trees, multiple parents, and repeated identical content.

The initial implementation may use loose objects. Packed-object optimization and repository maintenance are later concerns.

**Phase 2 exit criterion:** hot-git can create a valid commit chain entirely through Git's object database and refs, and a normal Git client can read the result.

## Phase 3 — refs and CAS

1. Implement a small ref API for reading and updating refs.
2. Implement expected-old-value updates as the concurrency primitive.
3. Make CAS failure explicit and typed; never convert a conflict into a silent last-writer-wins update.
4. Investigate `git update-ref --stdin` as a persistent Linux worker protocol, but do not make it a prerequisite for correctness.
5. Support transactional multi-ref updates if the underlying Git protocol proves portable and useful.
6. Test concurrent writers against the same ref.

The benchmark has already shown that ordinary `git update-ref <ref> <new> <old>` is fast on the VPS, so persistent ref IPC is an optimization rather than an architectural requirement.

**Phase 3 exit criterion:** concurrent writers can safely race on refs and observe deterministic CAS conflicts without corrupting or silently losing updates.

## Phase 4 — repository worker

Combine the pieces into a single per-repository worker/lifecycle abstraction:

```text
RepositoryManager
    |
    +-- repo-A -> RepositoryWorker
    +-- repo-B -> RepositoryWorker
    +-- repo-C -> RepositoryWorker
```

Requirements:

- lazy creation
- one worker per active repository
- shared by multiple agents/callers
- clean shutdown
- subprocess health checks
- optional idle eviction
- bounded resource usage

The worker should expose library operations, not expose its internal subprocess protocol to callers.

## Phase 5 — benchmark and optimization

Preserve and expand the benchmark suite from `personal-repo-mcp`:

- subprocess-per-object read
- persistent `cat-file --batch` read
- worker startup overhead
- treeless Git plumbing write
- worktree checkout write
- hot object write
- CAS update
- concurrent CAS conflicts

Track both absolute latency and speedup. Benchmark on Linux (the intended server environment) and Windows where supported.

The current VPS measurements provide a baseline:

- persistent reads: ~43x faster including worker startup
- hot object writes: ~2.47x faster than the existing treeless plumbing benchmark
- treeless writes: ~4.8x faster than the tested worktree workflow
- CAS ref updates: ~15 ms for the eight-worker benchmark

These numbers are evidence for the design, not acceptance thresholds.

## Phase 6 — production hardening

Before integrating hot-git into `personal-repo-mcp`:

- crash/restart tests
- concurrent object creation tests
- filesystem race tests
- ref-locking and CAS tests
- repository corruption/error handling
- packed repository tests
- large repository tests
- permission/read-only repository behavior
- resource limits
- SHA-256 repository investigation
- Windows compatibility assessment
- security review of direct object writes

## Future possibilities

Only after the library is correct:

- persistent `update-ref --stdin` worker on Linux
- Unix-domain-socket worker process
- optional standalone hot-git daemon
- Python async API
- integration with `personal-repo-mcp`
- integration with Aidos
- object caching where measurements justify it
- pack/index-aware optimizations
- multi-repository worker management in a separate process

## What hot-git is not

Hot-git is not intended to be:

- a replacement for Git
- a second source-of-truth database such as Redis
- a working-tree manager
- a Git hosting service
- an MCP server in Phase 1

The clean boundary is:

```text
personal-repo-mcp = agent-facing MCP interface
hot-git           = fast Git backend
Git               = authoritative repository/database
```
