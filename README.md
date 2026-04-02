# autoresearch

An autonomous experimentation loop for any software project. Drop it into any repo, describe your goal in `program.md`, and let an AI agent experiment, benchmark, and improve your code overnight — keeping changes that help, discarding ones that don't.

Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch), generalized beyond ML training into a language-agnostic plugin.

---

## How it works

1. You write `program.md` — describe what you want improved and what "better" means
2. The agent explores your project, decides what to change and how to benchmark it
3. It makes a focused change, runs the benchmark, and reports a metric
4. If the metric improved → `git commit` (keep). If not → `git reset` (discard)
5. Repeat, with a live terminal dashboard showing progress

The agent drives itself via tool calls (`read_file`, `write_file`, `run_command`, `list_files`, `report_metric`). It decides the benchmark and metric — you just describe the goal.

```
┌─ autoresearch ──────────────── iter 12/50 ── 1h 23m elapsed ─┐
│ Task: Optimize API response time                              │
├─ Current Experiment ──────────────────────────────────────────┤
│ "Caching database query results in memory"  Status: running...│
├─ Metric: api_latency_ms (lower is better) ────────────────────┤
│ Current: 142ms    Best: 98ms (iter 7)                        │
│ History: ▄▆█▅▃▂▄▃▂▁▂▃                                        │
├─ Last 5 Iterations ────────────────────────────────────────────┤
│  #11  112ms  ✗  "Added index on user_id"                     │
│  #10   98ms ★✓  "Connection pooling"                         │
│  #09  134ms  ✗  "Async refactor attempt"                     │
└──────────────────────────────── [q] quit  [p] pause ──────────┘
```

---

## Quick start

```bash
pip install autoresearch-plugin

cd your-project
autoresearch init        # drops program.md + autoresearch.yaml
```

Edit `program.md` to describe your task:

```markdown
# Task
Reduce the p50 latency of the /api/search endpoint.
The benchmark is: run `python bench/latency.py` and extract the p50_ms value.
Lower is better.
```

Edit `autoresearch.yaml` to set your model and API key:

```yaml
model: "anthropic/claude-sonnet-4-6"
max_iterations: 50
time_limit: "8h"
api_key: "${ANTHROPIC_API_KEY}"
```

Then run:

```bash
autoresearch run
```

---

## Configuration

`autoresearch.yaml` (created by `autoresearch init`):

```yaml
# Provider/model — supports anthropic, openai, ollama
model: "anthropic/claude-sonnet-4-6"

# Stop after N iterations (0 = unlimited)
max_iterations: 50

# Stop after this wall-clock time
time_limit: "8h"      # supports: 30m, 2h, 8h, etc.

# API key — use env var reference or paste directly
api_key: "${ANTHROPIC_API_KEY}"
```

### Supported models

| Config value | Provider |
|---|---|
| `anthropic/claude-sonnet-4-6` | Anthropic API |
| `anthropic/claude-opus-4-6` | Anthropic API |
| `openai/gpt-4o` | OpenAI API |
| `openai/gpt-4.1` | OpenAI API |
| `ollama/llama3` | Ollama (local, `localhost:11434`) |

---

## CLI commands

```bash
autoresearch init              # set up program.md + autoresearch.yaml in cwd
autoresearch run               # start the experiment loop
autoresearch run --iterations 20 --time-limit 2h
autoresearch status            # print results.tsv as a table
```

---

## Project structure

```
your-project/
├── program.md          ← describe your goal here (you write this)
├── autoresearch.yaml   ← model, iterations, time limit (you configure this)
├── results.tsv         ← experiment log (auto-generated, not committed)
└── ... your code ...
```

The plugin lives separately — nothing in your project gets modified except via the agent's own tool calls, which are all governed by what you write in `program.md`.

---

## How the loop works

```
autoresearch run
      │
      ▼
  Read program.md + project context
      │
      ▼
  ┌─── Agent (tool-call loop) ──────────────────┐
  │  list_files → read_file → write_file        │
  │  run_command (your tests/benchmark)         │
  │  report_metric(name, value, higher_better)  │
  └─────────────────────────────────────────────┘
      │
      ├── metric improved? → git commit (keep)
      └── metric worse?    → git reset  (discard)
      │
      ▼
  results.tsv updated → TUI refreshes → next iteration
```

Each iteration the agent makes **one focused change**, measures it, and decides. The git history becomes a clean record of what worked.

---

## results.tsv

After each run, results are appended to `results.tsv`:

```
iteration  commit   metric_name      value   higher_is_better  status   description
1          a1b2c3d  api_latency_ms   142.0   false             keep     baseline
2          b2c3d4e  api_latency_ms   98.0    false             keep     connection pooling
3          HEAD     api_latency_ms   112.0   false             discard  index on user_id
```

View a summary any time with:

```bash
autoresearch status
```

---

## Writing a good program.md

The quality of `program.md` directly determines result quality. Be specific:

**Good:**
```markdown
# Task
Improve test coverage of src/utils/parser.py.
Run `pytest --cov=src/utils/parser --cov-report=term-missing` and extract
the percentage from the "TOTAL" line. Higher is better.
Do not modify test files directly — improve the source code to be more testable.
```

**Too vague:**
```markdown
Make the code better.
```

Tips:
- Specify the exact command to run for benchmarking
- Tell it where to extract the metric from (stdout, a file, etc.)
- Specify which files are in/out of scope if needed
- Give it a hint about what kind of improvements to try

---

## License

MIT
