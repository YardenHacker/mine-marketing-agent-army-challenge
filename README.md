# The Agent Army Challenge — submission

Investigation, architecture, and one working agent for a Meta ad-buying automation system. The
four deliverables, in the order the work actually happened:

1. **[`INVESTIGATION.md`](INVESTIGATION.md)** — Task A. What the auto-rules actually did to the
   account over the week, quantified, plus two concrete bad-rule cases and every data issue found.
2. **[`ARCHITECTURE.md`](ARCHITECTURE.md)** — Task B. The POC design for an agent system that
   replaces most of a media buyer's decisions — topology, decision boundaries, economics, failure
   modes, data flow. No code; this is the design doc.
3. **[`RESULTS.md`](RESULTS.md)** — Task C. The one agent actually built and run end-to-end
   against the snapshot (2,064 real decisions, real Anthropic API calls), compared against what
   really happened, with an honest account of where it's weak. The working code itself,
   **[`agent/`](agent/)**, is part of this deliverable — it sits at the repo root alongside the
   write-up, not tucked away with the supporting material.
4. **[`DECISIONS.md`](DECISIONS.md)** — Task D. A running log of the whole build: what was asked,
   what was wrong, what got corrected, and the handful of decisions made deliberately rather than
   delegated. Kept live throughout 1-3, not written after the fact.

Everything else — the Task A analysis scripts, raw data, SQL, and real run output — is supporting
material and lives in [`supporting/`](supporting/).

## Setup

```bash
pip install -r requirements.txt
```

Python 3.11+ (built and run on 3.13). Only needed for Task C's real LLM call: create a `.env`
file in the repo root containing

```
ANTHROPIC_API_KEY=sk-ant-...
```

`.env` is gitignored — nothing in this repo depends on a specific key. Tasks A and B need no API
key at all (pure SQL/Python and a static design doc).

## How to reproduce each task

The working agent (`agent/`) sits at the repo root as its own deliverable. Everything else lives
under `supporting/`: `analysis/` is Task A's scripts, `sql/` / `dataset/` / `out/` / `assets/` are
the queries, raw data, real run output, and diagram image. Every script's relative paths are
written to work from *inside its own folder* — always `cd` into the specific folder below before
running anything in it.

**Task A — the investigation.** Every query is a standalone `.sql` file in `supporting/sql/`, run
from `supporting/analysis/` against the CSVs loaded into DuckDB tables (`db.py`):

```bash
cd supporting/analysis
python run_sql.py ../sql/01_join_coverage_and_response_split.sql   # and 02-10, same pattern
python impact_estimate.py      # the $ impact quantification behind INVESTIGATION.md sec1
python eda.py && python eda_followup.py && python eda_verify.py   # the data-issues catalogue (sec3)
```

Output: `supporting/out/turn_off_impact_detail.csv`, `supporting/out/budget_decrease_impact_detail.csv`.
Findings are written up in [`INVESTIGATION.md`](INVESTIGATION.md); every number in it traces to
one of these scripts.

**Task B — the architecture.** No code to run — [`ARCHITECTURE.md`](ARCHITECTURE.md) is the
deliverable. The one number in it that *is* re-derivable from data is the Screener flag rate:

```bash
cd supporting/analysis
python run_sql.py ../sql/10_screener_flag_rate.sql
```

The pipeline diagram is in the doc as both Mermaid source (renders on GitHub) and a static PNG
(`supporting/assets/agent-pipeline-diagram.png`, for viewers that don't render Mermaid).

**Task C — the Adset Decision Agent.** This is the one that costs money and needs the API key,
run from `agent/`:

```bash
cd agent
python run_decisions.py --estimate   # prints a cost estimate, makes zero API calls -- run this first
python run_decisions.py --run        # the real batch: 2,064 decisions, ~$2.20, writes ../supporting/out/decisions.jsonl
python compare_decisions.py          # joins decisions.jsonl against real rule/buyer history
python validate_thresholds.py        # checks the confidence thresholds against settled outcomes
python money_impact.py               # estimates $ impact of committed decisions vs. real actions
```

`run_decisions.py --run` is resumable — if it's interrupted or hits the hard cost ceiling
(`$6.00`, well under the $10 reimbursement cap), re-running it picks up where it left off rather
than re-paying for completed decisions. `supporting/out/decisions.jsonl` is already committed in
this repo from the actual run, so you can run `compare_decisions.py` / `validate_thresholds.py` /
`money_impact.py` immediately without an API key or spending anything — they only read the
existing output.

## Repo structure

```
INVESTIGATION.md / ARCHITECTURE.md / RESULTS.md / DECISIONS.md   the four required deliverables,
                                      in that order -- see the top of this file
README.md                            this file
agent/                               Task C's working code -- part of the RESULTS.md deliverable,
                                      not supporting material (llm_decision.py is the core
                                      judgment call; run_decisions.py runs the whole batch)
supporting/                          everything else -- Task A's scripts, data, SQL, run output
  analysis/                          Task A -- the investigation scripts
  sql/                               every query cited in INVESTIGATION.md, one file per finding
  dataset/                           the provided CSVs + README_DATA.md, unmodified
  out/                               every script's actual output from the real runs (not sample data)
  assets/                            the static pipeline diagram
  PLAN.md                            working scratch doc kept during the build -- not a required
                                      deliverable, left in for transparency into how the work was
                                      scoped and sequenced
```

## Where corners were cut

Stated directly rather than left for a reviewer to discover:

- **Task C builds one agent, the Analyst.** No Screener, Guardian-as-a-service, Executor, or
  Auditor process actually runs — `ARCHITECTURE.md` designs all five roles, but only the Analyst
  (plus a code-level stand-in for the Guardian's bounds checks) is real, working code. This was
  confirmed as the intended scope with the brief's own wording ("implement **one agent**").
- **No live execution, anywhere.** Every number in `RESULTS.md` is a backtest against the static
  snapshot. Nothing in this repo ever wrote to a real Meta account or moved real budget.
- **The money-impact and threshold-validation numbers (`RESULTS.md` sec5/sec7) rest on small
  samples** (n=18 to n=51) and a single-world approximation (assumes the realized outcome would
  have been about the same regardless of which action was taken). Both limitations are stated
  explicitly in the document itself, not just here.
- **The improvement loop (`RESULTS.md` sec4) is designed and pseudocoded, not running.** There's
  no real settled-outcome ledger accumulating yet — this snapshot is one week, and most decisions
  don't have enough follow-up data in it to learn from (see `RESULTS.md` for exactly which do).
- **The Screener's pacing condition (`ARCHITECTURE.md` sec3, condition 4) doesn't actually fire** —
  `meta.daily_budget` is on an unreconciled scale relative to real spend (a real data issue found
  in Task A, not fixed here), so the condition as specified is currently unreachable. Flagged in
  the document rather than quietly dropped.
- **`expected_profit_impact`** is in the Task C output schema but the model never populates it —
  left as a known, reported gap (`RESULTS.md` sec7) rather than investigated further.
- **Six ad accounts' worth of design (`ARCHITECTURE.md`), one week of one account's worth of
  actual run (`RESULTS.md`).** The architecture is written for the full six-account scale; the
  working agent only ran against what the snapshot actually contains.

## Time spent

**About 7 hours of active work**, spread across parts of two days (not counting the real
wall-clock time spent waiting on the batch run itself, which ran in the background while other
work continued, per `DECISIONS.md`). Most of it went to Task A's methodology (the counterfactual
design, and re-deriving it after the R04 bug) and Task C's debugging (two live bugs in the batch
run, then a second full pass diagnosing why the agent was too conservative and fixing it).
