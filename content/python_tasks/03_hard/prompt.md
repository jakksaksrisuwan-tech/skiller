# Hard — TaskScheduler

Suggested time: 40 minutes.

## Task
Implement a `TaskScheduler` class that orders tasks by their dependencies.

```python
class CycleError(Exception):
    pass

class TaskScheduler:
    def add(self, name: str, deps: list[str] = ()) -> None: ...
    def run_order(self) -> list[str]: ...
```

### Rules
- `add(name, deps)` registers a task. Calling `add` twice with the same name
  **merges** dependency lists (no duplicates). It is fine to declare a task
  before its dependencies are added — the graph is closed when `run_order` is
  called.
- `run_order()` returns task names in a valid topological order (a task always
  appears after all its dependencies).
- When several orderings are valid, return them in **alphabetical order among
  ready tasks** at each step (Kahn's algorithm with sorted ready queue).
- Unknown dependencies (referenced in `deps` but never `add`-ed themselves) are
  treated as **implicitly added with no dependencies**.
- A cycle anywhere in the dependency graph raises `CycleError`. The exception
  message must contain the names of at least two nodes participating in a cycle.

### Examples
```python
s = TaskScheduler()
s.add("build", ["compile"])
s.add("compile", ["lint"])
s.add("lint")
s.run_order()   # -> ["lint", "compile", "build"]

s = TaskScheduler()
s.add("a", ["b"])
s.add("b", ["a"])
s.run_order()   # -> raises CycleError
```

Hidden tests cover: alphabetical tie-breaking, implicit deps, idempotent re-add,
multi-component graphs, and self-dependency cycles (`add("x", ["x"])`).
