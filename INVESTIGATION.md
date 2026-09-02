# INVESTIGATION.md — Task A: Investigate before you automate

Leadership's suspicion: the auto-rules destroyed money last week — killing winners, letting
losers run. This document reconstructs what the 12 auto-rules actually did over the
2026-06-06 → 2026-06-12 window, across ACC-01…ACC-06, and quantifies the impact.

All queries referenced below live in `supporting/sql/*.sql`. All Python analysis lives in
`supporting/analysis/*.py`. Everything is re-runnable — see [README.md](README.md).

---

## 0. Before trusting the log: what actually happened vs. what was logged

The rule engine logs an attempt every time a rule's condition is met — not every attempt
succeeded. Splitting `rule_executions.csv` by its `response` column (`supporting/sql/01_join_coverage_and_response_split.sql`):

| response | count | meaning |
|---|---:|---|
| `SUCCESS` | 164 | the action actually took effect |
| `"No budget to change"` | 20 | rule engine short-circuited before calling the Meta API — the computed new budget rounded to the current one |
| `{"status":"error","type":"OAuthException","code":190,"message":"access token invalidated"}` | 30 | the API call failed — **nothing changed** |

**23% of the logged "actions" never happened.** Every number in this document that measures
"impact" uses only the 164 `SUCCESS` rows. Treating all 214 log rows as real actions would
overstate rule impact in both directions.

The 164/214 = 214 total also matches `auto_rules.csv`'s `firings` column exactly (sum = 214),
confirming the log is complete for the week — the discrepancy is entirely about which logged
attempts *took effect*, not about missing rows.

### The failures aren't random — they're one account's outage, and they broke the system's own safety net

All 30 failures belong to a **single ad account** (`9913405683583663`, ACC-04). Bounding the
window using genuine `SUCCESS` rows (not the ambiguous "No budget to change" no-ops, which can
short-circuit before ever calling the API and so don't prove the token was healthy) — the last
clean success before the outage is **2026-06-08 05:00**, and the first clean success after is
**2026-06-10 18:00**. That's roughly **61 hours** where this one account's connection to Meta
was broken, during which the rule engine kept retrying every ~30 minutes, unattended, with no
visible alert and no self-pause.

Worse: **8 of those 30 failures are R09 — the rule that exists specifically to undo other
rules' mistakes** (`Turn On | Automation Mistake - Today`). R09 has a **100% failure rate**:
every single time in this dataset it tried to fix something, the fix itself failed. See Case 1
below.

---

## 1. Reconstructing rule impact — methodology and assumptions

**The brief is explicit that there's no single correct way to do this — here is the method
used, and why, stated in full so it can be checked or disputed.**

Full detail: `supporting/analysis/impact_estimate.py` (heavily commented — the file itself is written to be
read as documentation of the method, not just code) and `supporting/sql/06_revenue_delay.sql`,
`supporting/sql/09_r04_null_check.sql`.

### 1.1 The two action families need two different counterfactuals

- **Turn OFF** (R01, R03, R04, R05, R06, R08, R11): the adset stops spending entirely. There is
  no post-action observation of "what it would have done" — we have to estimate.
- **Budget Decrease** (R02, R07, R10, R12): the adset keeps running, just at a lower budget. We
  can use its *actual* observed post-cut performance — a much more defensible method than pure
  extrapolation, because it's real data, not a projection.

### 1.2 Turn-OFF method — and a methodology bug caught along the way

The obvious first choice for "what would this adset have kept earning" is the trailing-3-day
figures already in `rule_executions.csv` (`last_3_days_roi_at_action`, `last_3_days_spend_at_action`).
The first version of this analysis used exactly that — and it silently produced **$0.00 impact
for R04 in every scenario**, which looked wrong for the single biggest rule (109 of 164 successful
executions, 51% of all rule activity). Checking why (`supporting/sql/09_r04_null_check.sql`): **0 of R04's
109 rows have a non-null trailing-3-day figure**, because R04 fires on adsets that are exactly
one day old — by construction, a one-day-old adset has no three-day trailing window. The method
wasn't finding "R04 has zero impact"; it was finding "this method can't see R04 at all," and
silently reporting that as a zero would have been a real error in the deliverable, not a
finding about the rules.

**Fix:** use the adset's own **settled same-day performance** from `daily_adset_performance.csv`
(`perf.spend`, `perf.roi` for that `adset_id` + `action_date`) instead. This is available for
essentially every row (perf join coverage is 100%, see §1.4 / `supporting/sql/01`), and it's also a *more
accurate* number than `today_roi_at_action` for the reason established in §1.4 below: same-day
ROI as seen mid-day systematically understates the day's true final ROI, so the settled figure
corrects for exactly the bias that would make a rule's decision look more justified than it was.

```
forgone_daily_profit_rate = perf.roi     for (adset_id, action_date)
forgone_daily_spend_rate  = perf.spend   for (adset_id, action_date)
forgone_profit = forgone_daily_spend_rate × forgone_daily_profit_rate × remaining_days_in_dataset
```
where `remaining_days_in_dataset` = days from `action_date + 1` through 2026-06-12 (the last date
in the snapshot — we don't extrapolate past what we can observe).

Two caveats stated rather than hidden:
- `perf.spend` on the kill date is itself probably reduced by the kill happening mid-day (the
  adset couldn't spend its full potential after being paused) — so our spend-rate is likely an
  **underestimate**, meaning the central/optimistic numbers below are conservative relative to
  reality, not inflated.
- Projecting one day's rate forward across multiple remaining days assumes stable performance,
  a strong assumption for adsets that are, in several cases, only 1–4 days old.

Three scenarios, varying which rate stands in for "what would have kept happening". **Revised
during review** — the first version floored the conservative rate at 0 whenever the settled ROI
was negative, which meant conservative could only ever show "money burned," never credit a rule
with "money saved." That made it structurally incomparable to central/optimistic (which both net
harm against savings) and produced a result that wasn't even between the other two. Fixed so all
three scenarios sit on one real, comparable scale:

| Scenario | Rate used |
|---|---|
| Conservative | `min(settled same-day ROI, last_3_days_roi_at_action)` where the trailing figure is available — the more skeptical of two independent readings; falls back to the settled ROI alone for R04 (no trailing figure exists for day-1 adsets, so there's nothing to be more skeptical against) |
| Central | settled same-day ROI as-is (can be negative → negative "forgone profit" = money *saved*) |
| Optimistic | `max(settled same-day ROI, last_3_days_roi_at_action)` where available — benefit of the doubt for an improving trend |

By construction, conservative ≤ central ≤ optimistic for every row, so the three totals now form
a real spectrum instead of three unrelated framings.

### 1.3 Budget-decrease method

For each cut, we look at the adset's actual perf rows in the window after the cut, up to the
next action on that adset (or end of dataset). We assume profit-per-dollar-spent is roughly
constant across a modest budget change (stated assumption — real diminishing returns exist but
aren't observable in this snapshot):

```
budget_ratio = old_budget / new_budget − 1        (the extra fraction that would have been spent)
forgone_profit = Σ over the window of: actual_daily_spend × budget_ratio × actual_profit_per_dollar_spent
```

### 1.4 The revenue-delay characterization (this gates the whole investigation)

Comparing what the rule engine *saw* at the moment of action (`today_roi_at_action`,
`spend_at_action`) against the *final settled* figure for that same adset-day
(`supporting/sql/06_revenue_delay.sql`), across all 164 successful executions:

- The gap between same-day-seen ROI and final ROI is **largest in the early morning hours**
  (04:00–08:00, average gap +0.25 to +0.48) and **shrinks to near zero by evening** — a clean,
  monotonic pattern. Revenue/conversion attribution is genuinely delayed within the day.
- **Spend reporting lags much less than revenue**: the median fraction of final spend already
  visible at action time is **92.4%**. The delay is specifically in revenue/conversion
  attribution, not in spend reporting — an important distinction for anything built on top of
  this data (poll spend freely; treat same-day ROI as provisional, especially before ~09:00).
- Pooled across all 164 actions: **11 (6.7%) were taken when the adset looked like a loser
  (negative ROI) at the moment of action, but the day finished at breakeven or better** (full list
  in `supporting/sql/08_all_flipped_cases.sql`). Only 1 action flipped the other way (looked like a winner
  mid-day, finished a loser). That 11:1 asymmetry is the direct, quantified evidence for
  leadership's "killed winners" suspicion — and it really is concentrated, not spread evenly:
  **R08 accounts for 4 of the 11** (on 3 unique adsets — see §2's supporting pattern), R02 for 3,
  and R01/R07/R10/R12 one each. **R04 — the single largest rule at 109 executions — accounts for
  zero of the 11**, confirmed by a dedicated, stricter search that came back empty
  (`supporting/sql/07_case_study_r04_killed_winner.sql`, later broadened into the unrestricted search in
  `supporting/sql/08` that produced the full 11-row list above).

### 1.5 Results

**Turn-off rules**, forgone profit by rule and scenario (`supporting/out/turn_off_impact_detail.csv` has
every row):

| rule_id | n | conservative | central | optimistic |
|---|---:|---:|---:|---:|
| R01 | 4 | -$0.93 | -$0.93 | -$0.54 |
| R03 | 17 | -$6.12 | -$6.12 | -$4.40 |
| R04 | 109 | -$374.54 | **-$374.54** | -$374.54 |
| R05 | 6 | -$37.99 | -$37.97 | -$2.47 |
| R06 | 1 | -$1.07 | -$1.07 | $0.06 |
| R08 | 13 | **-$76.82** | **-$54.75** | **$47.01** |
| R11 | 2 | -$0.30 | -$0.30 | -$0.04 |
| **Total** | **152** | **-$497.76** | **-$475.67** | **-$334.92** |

(R04's three scenarios are identical — no trailing-3-day figure exists for day-1 adsets, so
conservative/central/optimistic collapse to the single settled-ROI reading for all 109 rows.)

**Budget-decrease rules**, forgone profit from realized post-cut performance
(`supporting/out/budget_decrease_impact_detail.csv`):

| rule_id | n | forgone profit |
|---|---:|---:|
| R02 | 6 | -$0.20 |
| R07 | 1 | $0.00 |
| R10 | 2 | -$6.70 |
| R12 | 3 | -$0.11 |
| **Total** | **12** | **-$7.00** |

**Grand total, three scenarios:**

| Scenario | Net impact |
|---|---:|
| Conservative | **-$504.77 saved** |
| Central | **-$482.68 saved** |
| Optimistic | **-$341.92 saved** |

### 1.6 How to read this — don't just take the headline number

**All three scenarios now agree on direction**: the rules, as a whole, netted out as
money-saving this week, not money-burning — the range is narrower and more consistent than the
first version of this analysis showed (which had conservative disagreeing with the other two on
sign). This is driven almost entirely by R04 (109 firings, all clearly negative same-day ROI,
none of which flipped sign in the loser→winner check in §1.4). **This does not clear the
auto-rules of leadership's suspicion.** It means the suspicion is real but narrower than "the
rules destroyed money across the board": the damage is concentrated in a specific, identifiable
minority of actions, mostly from rules that ignore performance data (R08) or that were blocked
from acting at all by the outage (R09) — not spread evenly across all 214 logged attempts. See
§2 for exactly where.

R08 is the one rule where the scenarios genuinely disagree on *direction*, not just magnitude:
conservative says -$76.82 (net saved), optimistic says +$47.01 (net burned). That spread is the
signal, not noise — R08 has zero performance condition (it's a pure age gate), so unlike R04 its
13 actions really are a mixed bag of correct and incorrect kills, and no single scenario should
be trusted alone for this rule. The two case studies in §2 and the 33% flip rate noted there are
a more reliable read on R08 than any of the three dollar figures.

The risk isn't really captured by this week's dollar total at all — it's structural (see §2),
and a different week's data, with a different mix of ages and thresholds triggering, could
easily produce a larger burned figure from the exact same rule logic.

---

## 2. Two concrete cases a competent human would not have made

### Case 1 — The safety net that never once worked: R09 vs. the outage

**Adset `31314467522499`**, ACC-04, "easy-hearing-aids-program-58" campaign, created 2026-06-05
(1 day old on the day in question).

Timeline (`supporting/sql/03_case_study_31314467522499.sql`):

1. **06-08, 04:00** — R08 (`Turn OFF | Total Days = 4`, a pure age gate with **no performance
   condition at all**) fires and succeeds. At that moment `today_roi_at_action = -0.37`.
2. **06-08, 09:30 onward** — R09 (`Turn On | Automation Mistake - Today`) correctly identifies
   this as a mistake and tries to reactivate. At this point `today_roi_at_action` has already
   flipped to **+1.01** (the adset's tiny amount of pre-pause spend had turned profitable as
   more revenue attributed in). R09 retries **8 times** over the next 9 hours (09:30, 12:30,
   13:30, 14:30, 15:30, 16:30, 17:30, 18:30) — every attempt returns the identical
   `access token invalidated` error. **Every single attempt to fix the mistake failed.**
3. The adset never resumes. `daily_adset_performance.csv` shows spend = $0 for 06-09 through
   06-12 — it stayed dead for the rest of the week the data covers.
4. The day it was killed, the adset settled at spend $0.3175, revenue $0.635, **ROI +1.00 (a
   100% return)** — a tiny adset, but definitively a winner, not a loser.

**What the rule was missing:** R08's own kill decision was itself a case of the delayed-revenue
problem (§1.4) — a 4am reading on an adset with almost no spend yet is thin-sample noise, and
the day went on to settle strongly positive. But the more structurally important failure is
downstream: **the system's own admission that it made a mistake (R09 firing at all) was
completely unable to act on that admission**, because of an unrelated infrastructure fault that
nothing in the rule engine detected, alerted on, or paused itself for. A competent human
overseeing this account would have noticed a dead API connection within the ~9 hours R09 spent
retrying — the automation had no equivalent mechanism. This is not a threshold-tuning problem;
it's a missing guardrail (see `ARCHITECTURE.md`, when written, for the kill-switch/alerting
design this motivates).

*Financially small in isolation (this is a sub-$1/day adset) — included as Case 1 because it is
the cleanest, most fully-evidenced example of a structural failure mode, not because of its
dollar size. Case 2 below has real money attached.*

### Case 2 — R10 cuts the day's best performer on a near-breakeven morning reading

**Adset `31302925337341`**, ACC-04.

- **06-08, 05:00** — R10 (`Budget Decrease | -10 < ROI <= 5 | Budget >= 100$`, -15%) fires.
  At that moment: spend $70.45, `today_roi_at_action = -0.04` (essentially breakeven, just
  inside R10's trigger band). The logged budget change is `old_budget = $213.89 → new_budget =
  $254.00` — an *increase*, not the -15% decrease the rule is named for. This is the same
  inconsistency as Data Issue #8 below (decrease rules occasionally log `new_budget >
  old_budget`), so the direction of this specific budget change is unreliable in the log; what's
  well-evidenced and not in question is the rule firing on a near-breakeven, thin-morning-data
  reading of an adset that went on to be one of the day's best performers.
- **Settled end of day:** spend $264.06, revenue $321.50, **ROI +0.2175, profit $57.44** — this
  adset went on to be one of the strongest performers in the dataset that day.

**What the rule was missing:** a 5am reading of "essentially breakeven" on an adset that,
including three-day trailing context, was already a fine performer is exactly the kind of
signal §1.4 shows is least reliable — same-day ROI is most understated in the 04:00–08:00
window. R10's threshold treats a noisy, incomplete morning snapshot with the same confidence as
an end-of-day figure. The rule has no sense of *how much data it's looking at* — a $70 spend
reading at 5am and a $70 spend reading at 9pm are not equally trustworthy, but R10 treats them
identically.

*(A third, supporting pattern worth naming without treating as a full separate case: 3 of R08's
9 unique targets — 33% — settled with positive same-day ROI despite being killed on age alone,
with zero performance condition in the rule at all. R08 is a strong secondary example of the
same underlying issue as Case 1: a rule that doesn't look at performance data will periodically
kill a winner purely by chance, and 1-in-3 in this data is not a rare event.)*

---

## 3. Data issues encountered, and how each was checked

| # | Issue | How it was found | How it was handled |
|---|---|---|---|
| 1 | 23% of logged rule executions never took effect (30 API errors, 20 no-ops) | Grouped `rule_executions.response` (`supporting/sql/01`) | All impact analysis restricted to `response = 'SUCCESS'` rows only |
| 2 | The 30 API failures aren't random noise — they're a single account's ~61-hour outage window | Grouped failures by account + hour (`supporting/sql/02`), bounded the window using genuine `SUCCESS` timestamps rather than the ambiguous no-op responses (`supporting/sql/04`) | Treated as a real infrastructure event; became the basis for Case 1 and a Task B guardrail (alerting/kill-switch on repeated API failures per account) |
| 3 | Two non-overlapping `adset_id` formats (14-digit and 18-digit) across files | Length-distribution check + suffix-matching to rule out truncation | All views load `adset_id` as `VARCHAR` explicitly (`supporting/analysis/db.py`); confirmed 75/75 unique `rule_executions` adsets join cleanly to both `perf` and `meta` (`supporting/sql/01`) |
| 4 | `response` column contains raw JSON with embedded commas, which would corrupt column alignment under a naive CSV split | Manually verified during initial profiling before any real parser was in place | Used DuckDB's real CSV parser throughout; verified after loading that `rule_id` only ever takes values R01–R12 (`supporting/sql/01`, query 3) — confirms no column-shift occurred |
| 5 | `budget_level` looked corrupted during initial (naive, pre-tooling) profiling — showed fractional values like `0.1016` | Re-checked the same column through the real parser (`supporting/sql/04`) | Resolved: it cleanly takes only `adset`, `campaign`, or NULL. The earlier odd values were an artifact of a naive comma-split parse colliding with issue #3 above — a false alarm caught by re-verifying with proper tooling before it entered a deliverable |
| 6 | `meta.daily_budget` and `rule_exec.old_budget`/`new_budget` are on different, inconsistent scales for the same adset — ratios range ~100×–300×, not a fixed conversion factor | Joined the two on `adset_id` for all 75 rule-touched adsets (`supporting/sql/04`, `supporting/sql/05`) | Two hypotheses tested and ruled out: (a) CBO campaign-level budget pooling — ruled out, every affected campaign has exactly 1 sibling adset, and the mismatch occurs under ABO too; (b) a flat unit/currency conversion bug — ruled out, the ratio varies continuously (100, 133, 150, 160, 166, 185, 260, 300…) rather than sitting at one constant. **Root cause not resolved** — flagged explicitly rather than guessed. Handled by never comparing absolute dollar figures across the two systems; all impact analysis in §1 uses `rule_exec`'s own budget/spend figures internally and `perf`'s figures internally, never cross-system |
| 7 | `old_budget` sometimes disagrees with `current_budget_from_fb` (the live Meta-side reading) | Row count check comparing the two columns (`supporting/sql/01` profiling) — 64 of 214 rows differ | Noted as evidence the reporting system's view of "current budget" can be stale; not corrected (no way to know which is right from this snapshot), but flagged as a live-system risk for Task B (poll the source of truth, don't trust a cached budget figure before acting) |
| 8 | Some "Budget Decrease" rule executions show `new_budget > old_budget` (an increase, not a decrease) | Spot-checked while reviewing budget-decrease impact detail (§1.3 output) | Consistent with issue #7 — the reporting system's budget bookkeeping isn't fully reliable. Rows like this were included as-is in the impact calculation (the realized-performance method in §1.3 doesn't depend on the direction being correct, only on the actual budget values), but the inconsistency itself is reported here rather than silently smoothed over |
| 9 | R03 and R11 have overlapping trigger conditions (`positive_days = 0, total_days > 2` vs `> 3`) — R11's condition is a strict subset of a state R03 should already have caught | Read the 12 rule names carefully (`supporting/sql/` — no query needed, this is definitional) | Not independently verifiable from execution data alone (would need to see cases where R03 failed to fire but R11 did); flagged as a rule-set design smell worth resolving, not a data-quality issue per se |
| 10 | R02/R07/R12/R10's ROI trigger bands leave gaps (e.g. nothing covers `-0.50 < roi <= -0.30` outside R02's own band in some configurations) | Read the 12 rule names carefully, cross-checked thresholds against the README's percentage-vs-ratio convention | Same as #9 — a rule-set completeness observation, not something the data can resolve on its own |
| 11 | 72 rows in `daily_adset_performance.csv` are **true full-row duplicates** (every column identical, not just the join key) — 72 `(adset_id, date)` keys each appear twice | Grouped on the full row (not just the key) via `GROUP BY` and independently re-derived with a `row_number()` window function (`supporting/analysis/eda.py`, verified in `supporting/analysis/eda_verify.py` §V1–V2) | Checked whether this affected any Task A number: **no** — none of the 72 duplicated adsets appear in `rule_executions.csv` at all (`supporting/analysis/eda_followup.py` §B, re-confirmed via anti-join in `supporting/analysis/eda_verify.py` §V3). Left as-is in the raw file (not deduplicated in place) since Task A's queries join through `rule_exec` and never hit this; flagged for anyone doing a raw `SUM(spend)` off `perf` directly |
| 12 | `meta.language` has severe spelling/casing inconsistency — 34 raw string values collapse to ~20 real categories. English alone is spelled 4 ways (`en`, `EN ` with trailing space, `EN`, `English`); the pattern repeats for es/de/fr/pt/sv/ja/ar. One row is a literal single-space character, distinct from NULL | Full distinct-value listing with bracketed/length inspection to catch invisible whitespace (`supporting/analysis/eda.py` §5, `supporting/analysis/eda_followup.py` §I) | Every uppercase 2-letter code carries a trailing space, every lowercase one doesn't — too consistent to be typing error; most likely two source systems or import batches merged without normalization. Re-verified the collapsed totals sum exactly to all 7,129 `meta` rows (`supporting/analysis/eda_verify.py` §V4) before treating this as reliable. `language` was not used in any Task A calculation, so no impact analysis needed correction — flagged for Task B/data-hygiene attention (see §3.5) |
| 13 | 13 rows have `cr > 1` (a "conversion rate" over 100%) | Cross-referenced against `estimated_conversions > clicks` (`supporting/analysis/eda.py` §7, confirmed 13/13 in `supporting/analysis/eda_verify.py` §V6) | Not a data error: `estimated_conversions` comes from a multi-touch attribution model that can credit an adset with conversions beyond its own tracked clicks (view-through/cross-device). `cr` is therefore "attributed conversions ÷ own clicks," not a true bounded rate — worth documenting so nobody builds a rule assuming `cr <= 1` |
| 14 | `last_3_days_revenue_at_action` is non-null for 49 rows where `last_3_days_spend_at_action`/`last_3_days_roi_at_action` are null — all 49 are R04, day-1 adsets that by definition shouldn't have any 3-day trailing figure at all | Cross-tabulated null patterns across the three `last_3_days_*` columns (`supporting/analysis/eda_followup.py` §G), confirmed the full set (not a sample) is 100% R04/day-1 in `supporting/analysis/eda_verify.py` §V5 | **Unresolved** — either the revenue figure is computed under a looser/different gate than spend and ROI in the rule engine's context-building step, or it's picking up something attributable before the adset's own first day. Not used anywhere in the Task A impact calculation (`impact_estimate.py` only reads `last_3_days_roi_at_action`, which is reliably null here), so it didn't corrupt any number — but it's a real internal inconsistency worth escalating to whoever owns that pipeline |

**Checked and found no additional issues in:** row counts across all 5 files (verified against
`README_DATA.md`'s implicit expectations and internal consistency — `rule_executions` row count
matches the sum of `auto_rules.firings` exactly); date range coverage (all 7 days present,
2026-06-06 through 2026-06-12, confirmed via `GROUP BY date`); the `roi`/`ctr`/`cr` unit
conventions stated in `README_DATA.md` (spot-checked several rows by hand, then verified exactly
across all rows: `profit = revenue - spend` and `roi = profit/spend` hold to within floating-point
rounding for every row with `spend > 0`, `supporting/analysis/eda.py` §7); referential integrity across all 5
files (0 orphaned `adset_id`/`rule_id` values in any direction, `supporting/analysis/eda.py` §4); internal date
gaps within any single adset's active window — **re-verified on `count(DISTINCT date)` rather
than raw row count**, specifically because issue #11's duplicate rows could otherwise have masked
a real gap by inflating a row count without inflating date coverage; 0 true gaps, including
re-checked specifically on the 72 duplicate-affected adsets (`supporting/analysis/eda_verify.py`, ad hoc query,
not just `supporting/analysis/eda.py` §3's original weaker version); every categorical column other than
`language` (`effective_status`, `delivery_status`, `bid_strategy`, `budget_optimization`,
`objective`, `optimization_goal`, `budget_level`, rule `action`/`schedule`/`scope`, buyer
`event_type`/`object_type`) — small, consistent value sets, no casing or whitespace variants
(`supporting/analysis/eda.py` §5–6); the `bid_amount`/`roas_target` null pattern is a strict, zero-violation 1:1
function of `bid_strategy` (`supporting/analysis/eda_verify.py` §V7); and negative values in any monetary or rate
column (`supporting/analysis/eda.py` §7 — none found in spend, revenue, budgets, or bid amounts across any file).

**One precision correction caught on re-audit:** the null counts for `revenue`/`ctr`/`cr` quoted
in conversation while this investigation was underway (2,721 / 2,953 / 3,097) were measured on
the raw file, which includes issue #11's 72 duplicate rows — the true unique-row counts are
2,676 / 2,906 / 3,050 (each duplicate row with a null value contributes one extra count). The
*pattern* those counts support — null exactly where the relevant denominator is zero — is
unaffected and still holds at 100% either way, since duplicating a row duplicates the null flag
and the zero-denominator condition together. No number in the impact estimate (§1) used these
counts; this correction is scoped to the EDA section only.

### 3.5 Suggested ways to handle these problems

Grouped by what kind of fix each needs — most of these are for whoever owns the rule engine or
the ETL pipeline, not fixable from this snapshot alone:

**Infrastructure / alerting (issues #1, #2):**
- Add a circuit breaker: after N consecutive API failures on the same account (e.g. 3), stop
  retrying and page a human, instead of blindly retrying every 30 minutes for 61 hours.
- Distinguish retryable errors (rate limits, timeouts) from non-retryable ones
  (`access token invalidated` is never going to succeed on retry without human intervention —
  retrying it is pure waste and, worse, it silently ate R09's only chance to fix a real mistake).
- Emit a health-check metric per account (time since last successful API call) with an alert
  threshold well under 61 hours.

**Data pipeline / ingestion (issues #3, #4, #11, #12):**
- Normalize `adset_id` to one canonical format at ingestion (pick one, e.g. the 18-digit form,
  and maintain a crosswalk for the legacy 14-digit one) so every downstream system joins on a
  single consistent key instead of relying on every consumer to know both formats exist.
- Move the raw `response` JSON payload out of the wide CSV export into a separate normalized
  error-log table — reduces parsing risk for any downstream consumer using a naive parser (this
  investigation only avoided the risk because DuckDB's parser handles quoted embedded commas
  correctly; a less careful pipeline wouldn't).
- Add a uniqueness constraint (or a pre-load dedup step) on `(adset_id, date)` for the
  performance export, and investigate the export job for why duplicates occur (likely a
  retry-without-idempotency-key in whatever process generates this file).
- Normalize `language` at ingestion: lowercase + trim, then map known aliases (`EN`/`en`/`English`
  → one canonical `en`; `NO_LANGUAGE`/`no_language` → one canonical value) into a controlled
  vocabulary, with a validation step that rejects or quarantines anything outside it.

**Budget reconciliation (issues #6, #7, #8):**
- Add an explicit `budget_unit`/currency field to both the metadata and rule-engine systems so
  it's never ambiguous which scale a number is on.
- Before a rule *acts*, re-fetch the live budget from Meta rather than trusting a cached
  `old_budget` — or at minimum, abort the action and flag it if the cached value and
  `current_budget_from_fb` disagree beyond a small tolerance.
- Add a sanity assertion in the rule engine itself: a rule literally named "Decrease" should
  never be allowed to log (or apply) a `new_budget > old_budget` without raising an alert.

**Rule-set design (issues #9, #10):**
- Run a systematic threshold/coverage audit across all 12 rules — tabulate every ROI/day/budget
  band side by side to find overlaps (R03 vs R11) and gaps (the uncovered `-0.50 < roi <= -0.30`
  band) in one pass, rather than relying on manually reading rule names.
- Consolidate R11 into R03 (its condition is a strict subset) unless there's a deliberate reason
  for the separate rule that isn't visible from the data.

**Metric definitions (issue #13):**
- Rename or document `cr` precisely as "attributed conversions ÷ own clicks" rather than a
  standard bounded conversion rate, so a future rule author doesn't assume `cr <= 1` when writing
  a threshold.

**Needs engineering investigation, not fixable here (issue #14):**
- Find why `last_3_days_revenue_at_action` is populated under a different gate than
  `last_3_days_spend_at_action`/`last_3_days_roi_at_action` in the rule engine's context-building
  code, since as it stands the three columns can't be trusted to arrive or be absent together.

---

## 4. Assumptions, collected

1. Only `response = 'SUCCESS'` rows in `rule_executions.csv` represent real, effective actions.
2. Turn-off counterfactual: the adset's settled same-day performance is a reasonable proxy for
   its near-term trajectory, projected forward at a constant daily rate through 2026-06-12.
3. Budget-decrease counterfactual: profit-per-dollar-spent is roughly constant across the size
   of budget change actually observed in this data (all cuts were −15% to −40%).
4. Where `meta.daily_budget` and `rule_exec` budget figures disagree, `rule_exec`'s own figures
   are used for all rule-impact math (internally consistent with itself); `meta.daily_budget` is
   not used as a cross-check for these calculations, per data issue #6.
5. "Remaining days" for extrapolation purposes is capped at the last date in the snapshot
   (2026-06-12) — no extrapolation beyond the observed window.
6. The three turn-off scenarios are meant to be genuinely comparable — same net-of-savings basis,
   differing only in which of two available ROI readings is used (see §1.2 for the correction
   history behind this).
