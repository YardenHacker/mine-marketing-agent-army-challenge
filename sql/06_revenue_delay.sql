-- How much does same-day ROI (as seen by the rule engine at action time)
-- understate the FINAL settled ROI for that adset-day, and how does that
-- gap shrink as the day goes on? This is the single most load-bearing
-- number in the investigation: it's the mechanism behind "killed winners".
--
-- rule_exec.today_roi_at_action / spend_at_action = what the engine saw,
-- at a specific time of day, for action_date.
-- perf.roi / perf.spend for the same (adset_id, date) = the FINAL settled
-- figure for that whole day (perf is a snapshot taken after the fact).
SELECT
    extract(hour FROM re.action_time::TIMESTAMP) AS hour_of_day,
    count(*) AS n_actions,
    round(avg(re.today_roi_at_action), 4) AS avg_roi_seen_at_action,
    round(avg(p.roi), 4) AS avg_final_roi_that_day,
    round(avg(p.roi - re.today_roi_at_action), 4) AS avg_roi_gap,
    round(avg(re.spend_at_action), 4) AS avg_spend_seen_at_action,
    round(avg(p.spend), 4) AS avg_final_spend_that_day,
    round(avg(p.spend - re.spend_at_action), 4) AS avg_spend_gap
FROM rule_exec re
JOIN perf p ON p.adset_id = re.adset_id AND p.date = re.action_date::DATE
WHERE re.response = 'SUCCESS'
  AND re.today_roi_at_action IS NOT NULL
GROUP BY hour_of_day
ORDER BY hour_of_day;

-- same thing but as a single overall summary + how often the sign of ROI
-- flips entirely between "what the engine saw" and "final settled" (i.e.
-- the engine saw a loser but it finished the day a winner, or vice versa)
SELECT
    count(*) AS n,
    round(avg(re.today_roi_at_action), 4) AS avg_roi_seen,
    round(avg(p.roi), 4) AS avg_roi_final,
    round(avg(abs(p.roi - re.today_roi_at_action)), 4) AS avg_abs_gap,
    sum(CASE WHEN re.today_roi_at_action < 0 AND p.roi >= 0 THEN 1 ELSE 0 END) AS seen_loser_finished_winner,
    sum(CASE WHEN re.today_roi_at_action >= 0 AND p.roi < 0 THEN 1 ELSE 0 END) AS seen_winner_finished_loser,
    round(100.0 * sum(CASE WHEN re.today_roi_at_action < 0 AND p.roi >= 0 THEN 1 ELSE 0 END) / count(*), 1) AS pct_flipped_loser_to_winner
FROM rule_exec re
JOIN perf p ON p.adset_id = re.adset_id AND p.date = re.action_date::DATE
WHERE re.response = 'SUCCESS'
  AND re.today_roi_at_action IS NOT NULL;

-- how much does spend itself lag within the day? (distinguishes "revenue
-- attribution is delayed" from "spend reporting is also delayed")
SELECT
    round(avg(re.spend_at_action / NULLIF(p.spend, 0)), 4) AS avg_fraction_of_final_spend_seen,
    round(median(re.spend_at_action / NULLIF(p.spend, 0)), 4) AS median_fraction_of_final_spend_seen
FROM rule_exec re
JOIN perf p ON p.adset_id = re.adset_id AND p.date = re.action_date::DATE
WHERE re.response = 'SUCCESS' AND p.spend > 0;
