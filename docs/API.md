# hot-git integration API

This document defines the small public surface intended for server-side consumers such as `personal-repo-mcp`.

## Repository lifecycle

Create one `Repository` for each Git repository and keep it alive while the repository is hot. `Repository` owns the persistent `git cat-file --batch` reader and is a context manager.

```python
from hotgit import Repository, Editor

with Repository("/srv/repos/example") as repository:
    editor = Editor(repository)
```

For a server with multiple repositories, use `WorkerPool`/`RepositoryWorker` as the lifecycle layer and keep one worker per canonical repository path.

## Reading

`Repository.read_object(oid)` reads a Git object without a working tree.

`Editor.read_file(ref_or_commit, path)` resolves a ref or commit and returns the file bytes directly from Git's trees and blobs.

```python
content = editor.read_file("refs/heads/main", "src/app.py")
```

## Editing

`Editor.edit()` creates blobs, reconstructs trees, creates a commit, and publishes it with a compare-and-swap ref update.

```python
from hotgit import Change

result = editor.edit(
    "refs/heads/main",
    [
        Change("README.md", b"new contents\n"),
        Change("src/app.py", b"...\n"),
        Change("old.txt", None),
    ],
    "Update application",
    expected_ref=base,
)
```

No working tree is checked out or modified.

## Chaining

`EditResult` is intentionally chain-friendly:

- `result.base` is the ref value used as the expected old value.
- `result.commit` is the newly published commit.
- `result.tree` is its root tree.
- `result.ref` is the updated ref.
- `result.changed_paths` contains the paths supplied to the edit.

A caller can therefore carry `result.commit` forward as the next operation's `expected_ref`.

```text
base -> edit A -> commit A -> edit B -> commit B -> edit C
```

If another writer changes the ref before the next edit, the CAS operation fails with `RefConflictError` instead of silently overwriting it.

## Integration boundary

Consumers should depend on `Repository`, `Editor`, `Change`, `EditResult`, and `RefConflictError`. Git object/tree/ref implementation classes remain available but should normally be treated as lower-level primitives.

The MCP-facing layer should translate its existing tool arguments and result format into this API rather than exposing hot-git's internal object model.
