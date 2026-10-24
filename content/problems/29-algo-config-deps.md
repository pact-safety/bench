---
slug: algo-config-deps
title: Resolve config dependencies via topological order
difficulty: medium
time_bucket: 30
problem_type: code_compose
is_warmup: false
structural_tags: [algo, graph]
domain_tags: [training]
competency_tags: [bfs_dfs, topological_sort]
jd_signal_tags: [config, dependency_resolution]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

Your experiment config has fields that reference other fields:

```
{
  "model_name": "llama_7b",
  "data_dir": "/data/${dataset}",
  "checkpoint_dir": "${data_dir}/checkpoints/${model_name}",
  "dataset": "openwebtext",
  "log_dir": "${checkpoint_dir}/logs"
}
```

Resolve all `${name}` references. Order the resolution so each field is
resolved only after its dependencies have been. Detect cycles and raise
`ValueError("cycle: " + comma_separated_chain)`.

Field values that are strings may contain zero or more `${name}`
references. Non-string values pass through unchanged. References to
missing fields raise `KeyError(name)`.

```
def resolve(config: dict) -> dict
```

## Starter

```
import re


def resolve(config):
    pass
```

## Solution

```
import re

REF = re.compile(r"\$\{(\w+)\}")


def resolve(config):
    # Build dependency graph: name -> [names it depends on].
    deps = {}
    for k, v in config.items():
        deps[k] = REF.findall(v) if isinstance(v, str) else []

    resolved = {}
    visiting = set()

    def visit(name, chain):
        if name in resolved:
            return resolved[name]
        if name in visiting:
            cycle = chain[chain.index(name):] + [name]
            raise ValueError("cycle: " + ",".join(cycle))
        if name not in config:
            raise KeyError(name)
        visiting.add(name)
        value = config[name]
        if isinstance(value, str):
            def sub(m):
                return str(visit(m.group(1), chain + [name]))
            value = REF.sub(sub, value)
        resolved[name] = value
        visiting.remove(name)
        return value

    for k in list(config.keys()):
        visit(k, [])
    return resolved
```

## Tests

```
cfg = {
    "model_name": "llama_7b",
    "data_dir": "/data/${dataset}",
    "checkpoint_dir": "${data_dir}/checkpoints/${model_name}",
    "dataset": "openwebtext",
    "log_dir": "${checkpoint_dir}/logs",
}
out = resolve(cfg)
assert out["data_dir"] == "/data/openwebtext"
assert out["checkpoint_dir"] == "/data/openwebtext/checkpoints/llama_7b"
assert out["log_dir"] == "/data/openwebtext/checkpoints/llama_7b/logs"

# Non-string passthrough
cfg2 = {"a": 42, "b": "${a}_x", "c": [1, 2, 3]}
out2 = resolve(cfg2)
assert out2["a"] == 42
assert out2["b"] == "42_x"
assert out2["c"] == [1, 2, 3]

# Cycle detection
cfg3 = {"a": "${b}", "b": "${c}", "c": "${a}"}
try:
    resolve(cfg3)
except ValueError as e:
    assert "cycle:" in str(e), str(e)
else:
    raise AssertionError("expected cycle ValueError")

# Missing reference
cfg4 = {"a": "${b}"}
try:
    resolve(cfg4)
except KeyError as e:
    assert "b" in str(e)
else:
    raise AssertionError("expected KeyError")

print("OK")
```

## Key insight

Lazy DFS resolution with a `visiting` set is the cleanest topological
order for this — you don't have to compute the full DAG upfront, and
cycle detection drops out of the recursion. Iterative Kahn's algorithm
also works but needs more machinery for nested string substitution.

## Pitfalls

- The cycle message must include the chain to be useful for debugging.
  A plain "cycle detected" hides which fields are involved.
- Substituting via `re.sub` with a function lets you recurse into each
  match — straightforward but easy to forget that `m.group(1)` is the
  *name* inside the braces, not the whole match.
- Non-string values must pass through. Real configs have integers,
  booleans, and nested dicts; only strings get reference expansion.
