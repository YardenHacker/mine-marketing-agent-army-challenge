-- Does account 9913405683583663 have any genuine SUCCESS (real budget change,
-- not a short-circuited no-op) during the 06-08/06-10 window? This bounds
-- the actual outage more precisely than just "OAuth error present".
SELECT action_time, rule_id, adset_id, response, old_budget, new_budget
FROM rule_exec
WHERE account_id = '9913405683583663'
  AND action_time::TIMESTAMP BETWEEN '2026-06-08 00:00:00' AND '2026-06-11 00:00:00'
ORDER BY action_time;

-- budget_level: what values does it actually take, and what does a sample
-- of the odd-looking numeric ones look like in full context? (possible
-- column-shift / mis-parse, or a genuine third budget_level type)
SELECT budget_level, count(*) AS n
FROM rule_exec
GROUP BY budget_level
ORDER BY n DESC;

SELECT action_date, rule_id, adset_id, old_budget, new_budget, set_budget,
       current_budget_from_fb, budget_level, response
FROM rule_exec
WHERE budget_level NOT IN ('adset', 'campaign') OR budget_level IS NULL
ORDER BY rule_id
LIMIT 20;

-- the $1.27 vs $127 mystery: compare rule_exec budgets to meta.daily_budget
-- for the same adset, across all 75 adsets that appear in rule_exec. Is a
-- ~100x gap common (systemic unit mismatch) or a one-off?
SELECT
    re.adset_id,
    re.old_budget AS rule_exec_old_budget,
    m.daily_budget AS meta_daily_budget,
    round(m.daily_budget / NULLIF(re.old_budget, 0), 2) AS ratio
FROM (SELECT DISTINCT adset_id, old_budget FROM rule_exec WHERE old_budget IS NOT NULL) re
JOIN meta m ON m.adset_id = re.adset_id
ORDER BY ratio DESC NULLS LAST
LIMIT 20;
