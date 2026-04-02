# autoresearch plugin — Architecture Plan

## Overview
A CLI tool that generalizes the autoresearch loop for any project.
Instead of training ML models, an LLM agent:
1. Reads `program.md` (task description written by the user)
2. Explores the project, decides what to change and what benchmark to use
3. Edits source code + writes/runs tests/benchmarks via tool calls
4. Reports a metric via `report_metric` tool
5. CLI keeps the change (git commit) if improved, discards (git reset) if not
6. Repeats until `max_iterations` or `time_limit` hit
7. Live TUI dashboard shows progress throughout

---

## Project Structure
```
autoresearch/
├── pyproject.toml
├── autoresearch.yaml          (dropped by `autoresearch init`, user edits)
├── program.md                 (dropped by `autoresearch init`, user edits)
└── autoresearch/
    ├── __init__.py
    ├── cli.py                 # typer CLI: init, run, status
    ├── loop.py                # main experiment loop
    ├── agent.py               # LLM agentic loop (tool call orchestration)
    ├── tools.py               # tool definitions + execution
    ├── git_ops.py             # commit, reset, diff, status helpers
    ├── tui.py                 # rich live dashboard
    ├── config.py              # autoresearch.yaml loader (pydantic)
    ├── providers/
    │   ├── __init__.py
    │   ├── base.py            # abstract LLMProvider interface
    │   ├── anthropic.py       # Anthropic SDK
    │   ├── openai.py          # OpenAI SDK
    │   └── ollama.py          # OpenAI-compatible at localhost:11434
    └── templates/
        ├── program.md         # task template
        └── autoresearch.yaml  # config template
```

---

## CLI Commands
```
autoresearch init              # drops program.md + autoresearch.yaml in cwd
autoresearch run               # starts the loop with TUI
autoresearch run --iterations 20 --time-limit 2h
autoresearch status            # show results.tsv summary
```

---

## Config (autoresearch.yaml)
```yaml
model: "anthropic/claude-sonnet-4-6"   # provider/model-name
max_iterations: 50
time_limit: "8h"                        # optional, e.g. "30m", "2h", "8h"
api_key: "${ANTHROPIC_API_KEY}"         # env var expansion supported
```

Provider routing: split `model` on first `/`
- `anthropic/*`  → Anthropic SDK
- `openai/*`     → OpenAI SDK  
- `ollama/*`     → OpenAI-compatible at http://localhost:11434/v1

---

## Agent Tools
The LLM is given these tools each iteration:

| Tool | Description |
|------|-------------|
| `read_file` | Read a file from the project |
| `write_file` | Write/overwrite a file |
| `run_command` | Run a shell command, returns stdout/stderr |
| `list_files` | List files matching a glob pattern |
| `report_metric` | Signal end of experiment + metric value |

`report_metric` schema:
```json
{
  "metric_name": "string",        // e.g. "test_pass_rate", "api_latency_ms"
  "value": "number",
  "higher_is_better": "boolean",
  "description": "string"         // what change was made this iteration
}
```

The loop detects `report_metric` call → evaluates → keep/discard.

---

## Experiment Loop (loop.py)
```
read program.md
load config
init git state (record HEAD)

for iteration in 1..max_iterations:
    git stash / reset to clean state if previous was discarded
    
    result = agent.run(project_context, task, history)
    # agent internally calls tools until report_metric is called
    
    metric = result.metric
    is_better = compare(metric, best_metric)
    
    if is_better:
        git commit -m f"iter {i}: {metric.description} ({metric.value})"
        best_metric = metric
        status = "keep ✓"
    else:
        git reset --hard HEAD
        status = "discard ✗"
    
    log to results.tsv
    tui.update(iteration, metric, status, history)
    
    if time_limit_exceeded: break
```

---

## TUI Dashboard (tui.py, using `rich`)
```
┌─ autoresearch ──────────────── iter 12/50 ── 1h 23m elapsed ─┐
│ Task: Optimize the API response time                          │
├─ Current Experiment ──────────────────────────────────────────┤
│ "Caching database query results in memory"                    │
│ Status: running...                                            │
├─ Metric: api_latency_ms (lower is better) ────────────────────┤
│ Current: 142ms    Best: 98ms (iter 7)                        │
│ History: ▄▆█▅▃▂▄▃▂▁▂▃                                        │
├─ Last 5 Iterations ───────────────────────────────────────────┤
│  #11  112ms  ✗  "Added index on user_id"                     │
│  #10   98ms  ✓  "Connection pooling"   ← best                │
│  #09  134ms  ✗  "Async refactor"                             │
└────────────────────────────── [q] quit  [p] pause ────────────┘
```

---

## results.tsv schema
```
iteration  commit    metric_name        value   higher_is_better  status   description
1          a1b2c3d   api_latency_ms     142.0   false             keep     baseline measurement
2          b2c3d4e   api_latency_ms     98.0    false             keep     connection pooling
3          HEAD      api_latency_ms     112.0   false             discard  index on user_id
```

---

## Provider Interface (providers/base.py)
```python
class LLMProvider(ABC):
    @abstractmethod
    def call(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str,
    ) -> ProviderResponse:
        ...

@dataclass
class ProviderResponse:
    text: str | None
    tool_calls: list[ToolCall]
    stop_reason: str   # "tool_use" | "end_turn" | "stop"
```

---

## Dependencies
- `typer` — CLI framework
- `rich` — TUI / live dashboard
- `pydantic` — config validation
- `pyyaml` — YAML parsing
- `gitpython` — git operations
- `anthropic` — Anthropic provider
- `openai` — OpenAI + Ollama provider
- `python-dotenv` — env var expansion in config

---

## Implementation Chunks (for parallel worktrees)
1. **chunk/setup-config-providers** — pyproject.toml, config.py, providers/
2. **chunk/tools-gitops**           — tools.py, git_ops.py
3. **chunk/tui-cli**                — tui.py, cli.py
4. **chunk/loop-agent-templates**   — loop.py, agent.py, templates/
