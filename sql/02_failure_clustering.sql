-- Do the 30 API failures cluster in time (one outage window) or by account
-- (one account's token died)? A real "access token invalidated" failure
-- should hit everything on that account from the moment the token broke
-- onward, regardless of which rule is asking.

SELECT
    account_id,
    date_trunc('hour', action_time::TIMESTAMP) AS hour,
    count(*) FILTER (WHERE response LIKE '{%error%') AS failed,
    count(*) FILTER (WHERE response = 'SUCCESS') AS success,
    count(*) AS total
FROM rule_exec
GROUP BY account_id, hour
HAVING count(*) FILTER (WHERE response LIKE '{%error%') > 0
ORDER BY account_id, hour;

-- min/max action_time of failures, and whether the SAME account has
-- successful executions before/after the failure window (proves the token
-- error was real and time-bounded, not a permanent dead account)
SELECT
    account_id,
    min(action_time) FILTER (WHERE response LIKE '{%error%') AS first_failure,
    max(action_time) FILTER (WHERE response LIKE '{%error%') AS last_failure,
    min(action_time) FILTER (WHERE response = 'SUCCESS') AS first_success,
    max(action_time) FILTER (WHERE response = 'SUCCESS') AS last_success,
    count(*) FILTER (WHERE response LIKE '{%error%') AS n_failed
FROM rule_exec
GROUP BY account_id
HAVING count(*) FILTER (WHERE response LIKE '{%error%') > 0
ORDER BY n_failed DESC;

-- all 8 R09 (Automation Mistake reactivation) executions in full detail --
-- these are candidates for the A3 "concrete case" writeup
SELECT action_date, action_time, account_id, adset_id, old_budget, new_budget,
       set_budget, response, today_roi_at_action, last_3_days_roi_at_action
FROM rule_exec
WHERE rule_id = 'R09'
ORDER BY action_time;
