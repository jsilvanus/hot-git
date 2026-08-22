# hot-git

`hot-git` is a Python library for fast, server-oriented access to Git repositories without requiring a working-tree checkout.

It is designed for long-lived processes such as MCP servers, agent runtimes, development services, and other systems that repeatedly read and modify the same repositories.

## Why hot-git?

Git is already the source of truth. The problem for a long-lived server is the cost of repeatedly starting Git processes and, for many mutations, maintaining a working tree that the server does not actually need.

hot-git keeps Git's storage model while making the hot paths persistent and treeless:

- persistent `git cat-file --batch` object reads;
- direct Git object creation for blobs, trees, and commits;
- tree editing without checking out files;
- atomic ref updates using Git CAS semantics;
- one reusable worker per repository;
- normal Git repositories remain directly usable by Git itself.

hot-git does **not** introduce a second database or replace Git's object database.

## Current status

The library is currently at **0.2.x** and is being prepared for integration with `personal-repo-mcp`.

The core read, treeless edit, multi-file change, worker lifecycle, and ref-CAS paths are implemented and benchmarked. The next integration step is to use hot-git as a backend inside the MCP server while retaining the existing Git backend as a fallback.

This is an engineering project rather than a promise of API stability. Until a 1.0 release, applications should pin the version they use.

## Installation

Install from a tagged GitHub release once a release tag is available:

```bash
pip install "git+https://github.com/jsilvanus/hot-git.git@v0.2.0"
```

For local development:

```bash
pip install -e .
```

Python 3.11 or newer is required.

## Basic usage

### Read a Git object

```python
from hotgit import Repository

with Repository("/path/to/repository") as repo:
    obj = repo.read_object("<object-id>")
    print(obj.type)
    print(obj.data)
```

The repository owns a persistent object reader. Reusing the same `Repository` instance is therefore important for workloads with many reads.

### Make a treeless edit

```python
from hotgit import Change, Editor, Repository

with Repository("/path/to/repository") as repo:
    editor = Editor(repo)
    base = editor.refs.get("refs/heads/main")

    result = editor.edit(
        "refs/heads/main",
        [
            Change("README.md", b"new contents\n"),
            Change("docs/example.txt", b"example\n"),
        ],
        "update documentation",
        expected_ref=base,
    )

    print(result.commit)
```

The edit creates Git objects and publishes the resulting commit with compare-and-swap semantics. It does not check out or modify the working tree.

## Concurrency

Ref publication uses the expected-old ref value. If another writer changes the ref first, the operation fails with a ref conflict instead of silently overwriting that writer.

This makes hot-git suitable for agent workflows where multiple operations may target the same repository.

For chained operations, the previous `EditResult.commit` can become the expected base for the next operation:

```text
A(base=X) -> commit A
B(base=A) -> commit B
C(base=B) -> commit C
```

A higher-level caller such as an MCP `chain_command` implementation can carry this commit value through the chain.

## Repository workers

For a long-lived server, use `RepositoryWorker` or `WorkerPool` rather than constructing a new repository object for every request.

The intended model is:

```text
server
  |
  +-- repository A -> one hot worker
  +-- repository B -> one hot worker
  +-- repository C -> one hot worker
```

Workers share the persistent read path and serialize repository mutations where necessary. `WorkerPool` creates workers lazily and keys them by canonical repository path.

## Architecture

```text
Application / MCP server
          |
          v
  RepositoryWorker
          |
   +------+-------+----------------+
   |              |                |
   v              v                v
ObjectReader   ObjectStore       RefStore
   |              |                |
cat-file       blob/tree/commit    CAS refs
--batch             |
                    v
               TreeBuilder
                    |
                    v
               Git object DB
```

The working tree is deliberately outside this path.

## Performance

The repository contains repeatable benchmarks under `benchmarks/` comparing the library with ordinary Git subprocess operations and treeless Git plumbing.

The current Windows benchmark showed approximately:

- **268×** faster hot object reads than starting a Git process for every object;
- **128×** faster reads including persistent-reader startup for the tested 500-read workload;
- **2.27×** faster library writes than ordinary worktree Git;
- **4.41×** faster library writes than the tested subprocess-heavy treeless plumbing path.

These are benchmark results, not universal performance guarantees. Run the benchmarks on the target server and workload before making capacity assumptions.

Example:

```bash
python3 benchmarks/library_benchmark.py
```

Larger workload:

```bash
python3 benchmarks/library_benchmark.py --files 10000 --reads 5000 --writes 1000
```

## Compatibility

hot-git writes ordinary Git objects and refs. The resulting repositories can be inspected and operated on with normal Git commands.

The initial scope is SHA-1 repositories. SHA-256 repository support is intentionally deferred.

A working tree may still exist for a repository used by hot-git; hot-git simply does not require or modify it for its treeless operations.

## Development

Run the test suite with:

```bash
pytest -q
```

Run the benchmark suite with:

```bash
python3 benchmarks/library_benchmark.py
```

The benchmark suite also contains the earlier experimental hot-worker tests used to validate the architecture.

## Integration target: personal-repo-mcp

The primary immediate consumer is `personal-repo-mcp`.

The planned integration keeps the MCP interface stable while introducing a repository backend boundary:

```text
MCP tool
   |
   v
Repository backend
   |
   +-- existing Git backend
   |
   +-- hot-git backend
```

The existing backend remains available during the transition. hot-git should be selectable per deployment or repository until the integration has been exercised in real workloads.

## Design goals

1. Keep Git authoritative.
2. Avoid unnecessary working-tree operations.
3. Reuse expensive long-lived Git processes.
4. Make concurrent ref updates explicit and safe.
5. Keep the high-level API small enough for MCP and agent runtimes.
6. Preserve compatibility with ordinary Git tooling.
7. Optimize only after measuring the actual workload.

## License

MIT
