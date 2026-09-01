-- Is last_3_days_roi_at_action NULL for R04 (day-1 adsets, by definition no
-- 3-day trailing window exists yet)? If so, the trailing-rate counterfactual
-- method is inapplicable to R04 specifically -- not evidence R04 had zero
-- impact, evidence the method can't measure R04 at all.
SELECT
    rule_id,
    count(*) AS n,
    count(last_3_days_roi_at_action) AS n_with_trailing_roi,
    count(today_roi_at_action) AS n_with_today_roi,
    round(avg(today_roi_at_action), 4) AS avg_today_roi
FROM rule_exec
WHERE response = 'SUCCESS'
GROUP BY rule_id
ORDER BY n DESC;

-- R04 rows specifically, full detail on a sample
SELECT action_date, adset_id, total_days_at_action, spend_at_action,
       today_roi_at_action, last_3_days_roi_at_action, last_3_days_spend_at_action,
       old_budget, new_budget
FROM rule_exec
WHERE rule_id = 'R04' AND response = 'SUCCESS'
LIMIT 10;
