# Hot Git Worker Benchmark

This benchmark tests the hypothesis behind a future treeless Git worker:

> Keeping a Git object process alive and using `git cat-file --batch` can be substantially faster than spawning a new Git process for every object read.

It deliberately does **not** implement the future MCP worker. It is a small, isolated experiment that compares Git access patterns and is intended to evolve toward an agent-like workload.

## Current benchmark

`benchmark.py` compares:

1. spawning a Git process for each blob read;
2. one persistent `git cat-file --batch` process.

It also includes a repeated-read case. This gives us a baseline for a future in-process cache.

## Requirements

- Python 3.11+
- Git available as `git` on `PATH`
- no project dependencies

## Run

From the repository root:

```bash
python benchmarks/hot-git-worker/benchmark.py
```

Optional parameters:

```bash
python benchmarks/hot-git-worker/benchmark.py --files 10000 --reads 5000
```

The benchmark creates a temporary Git repository and removes it when finished.

## Next benchmark stages

### Stage 2 — tree traversal and `read_file`

Measure the complete path:

```text
commit/ref -> tree traversal -> path lookup -> blob -> content
```

Compare ordinary Git invocation with a persistent worker. Include repeated paths and paths from the same commit.

### Stage 3 — multi-file reads

Benchmark agent-like requests for 1, 10, 100, and 1000 files. Compare sequential requests with batched object access.

### Stage 4 — treeless edits

Prototype the object operations needed for an edit:

```text
read base tree
  -> create blob(s)
  -> construct tree(s)
  -> create commit
```

Do not update a shared ref unless specifically testing ref contention.

### Stage 5 — concurrent workers

Run multiple independent workers against the same packed repository. Measure throughput, latency, CPU, memory, object reads, and failures at increasing concurrency.

### Stage 6 — concurrent ref updates

Test compare-and-swap style updates:

```text
base = X
agent A -> commit A -> update ref if X
agent B -> commit B -> update ref if X
```

Exactly one competing update should succeed. This validates the concurrency primitive needed by the future chain/treeless design.

## Measurements

Do not report only elapsed time. Where practical capture:

- operations/sec;
- p50/p95/p99 latency;
- bytes returned;
- CPU time/usage;
- peak RSS;
- repository size;
- packed object size;
- Git subprocess count;
- failures/conflicts.

## Interpretation

The goal is **not** to prove that Git is always faster than another database. The question is whether:

> native packed Git + a long-lived object worker is fast enough that another persistence technology is unnecessary.

Only if that architecture is demonstrably insufficient should SQLite, Redis, RocksDB, or another acceleration layer be evaluated.

The current microbenchmark is therefore only the first step; the next useful result is the representative tree/read/edit/concurrency benchmark described above.
