-- Theory: campaign_adset_metadata.daily_budget reflects the CAMPAIGN's
-- configured budget under CBO (Campaign Budget Optimization), while
-- rule_exec's old_budget/new_budget reflect the actual per-adset allocation
-- tracked by the rule engine. If true, budget_optimization should be 'CBO'
-- for the mismatched rows, and the ratio should roughly track how many
-- sibling adsets share that campaign's budget.
SELECT
    re.adset_id,
    m.campaign_id,
    m.budget_optimization,
    re.old_budget AS rule_exec_budget,
    m.daily_budget AS meta_budget,
    round(m.daily_budget / NULLIF(re.old_budget, 0), 2) AS ratio,
    (SELECT count(*) FROM meta m2 WHERE m2.campaign_id = m.campaign_id) AS sibling_adsets_in_campaign
FROM (SELECT DISTINCT adset_id, old_budget FROM rule_exec WHERE old_budget IS NOT NULL) re
JOIN meta m ON m.adset_id = re.adset_id
ORDER BY ratio DESC NULLS LAST
LIMIT 20;

-- budget_optimization breakdown for ALL adsets that appear in rule_exec,
-- split by whether their budget matches metadata (ratio ~1) or not
SELECT
    m.budget_optimization,
    count(*) AS n,
    round(avg(m.daily_budget / NULLIF(re.old_budget, 0)), 2) AS avg_ratio
FROM (SELECT DISTINCT adset_id, old_budget FROM rule_exec WHERE old_budget IS NOT NULL) re
JOIN meta m ON m.adset_id = re.adset_id
GROUP BY m.budget_optimization;
