-- Defines the concrete Screener flagging rule (previously just an assumed "~20%") and
-- measures what fraction of active adsets it actually flags, on each of the last 3 days,
-- using the real data. Trailing 3-day ROI/spend are computed with window functions since
-- perf doesn't carry them precomputed for arbitrary dates (only rule_exec does, and only
-- at the moments a rule fired).

WITH daily AS (
    SELECT
        p.adset_id,
        p.date,
        p.spend,
        p.roi,
        p.profit,
        p.spend_day_no,
        m.effective_status,
        m.daily_budget,
        -- trailing 3-day figures ending the PRIOR day (what would have been known
        -- at the start of today, mirroring rule_exec's last_3_days_* semantics)
        sum(p.spend) OVER (
            PARTITION BY p.adset_id ORDER BY p.date
            ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING
        ) AS trailing_3d_spend,
        sum(p.profit) OVER (
            PARTITION BY p.adset_id ORDER BY p.date
            ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING
        ) AS trailing_3d_profit,
        -- days since this adset's most recent rule OR buyer action, as of this date
        (
            SELECT min(date_diff('day', a.d, p.date))
            FROM (
                SELECT action_date::DATE AS d FROM rule_exec re WHERE re.adset_id = p.adset_id AND re.response='SUCCESS'
                UNION ALL
                SELECT action_time::DATE AS d FROM buyer b WHERE b.adset_id = p.adset_id
            ) a
            WHERE a.d <= p.date
        ) AS days_since_last_action
    FROM perf p
    JOIN meta m ON m.adset_id = p.adset_id
    WHERE m.effective_status = 'ACTIVE'
),
flagged AS (
    SELECT *,
        trailing_3d_profit / NULLIF(trailing_3d_spend, 0) AS trailing_3d_roi,
        (p_spend_day_no <= 2) AS flag_new,
        (trailing_3d_spend IS NOT NULL AND trailing_3d_profit / NULLIF(trailing_3d_spend,0) <= -0.30) AS flag_bad_trend,
        (trailing_3d_spend IS NOT NULL AND trailing_3d_profit / NULLIF(trailing_3d_spend,0) >= 0.30) AS flag_good_trend,
        (spend >= 0.7 * daily_budget) AS flag_pacing_fast,
        (days_since_last_action IS NULL OR days_since_last_action >= 3) AS flag_stale_review
    FROM (SELECT *, spend_day_no AS p_spend_day_no FROM daily)
)
SELECT
    date,
    count(*) AS active_adsets,
    count(*) FILTER (WHERE flag_new) AS n_new,
    count(*) FILTER (WHERE flag_bad_trend) AS n_bad_trend,
    count(*) FILTER (WHERE flag_good_trend) AS n_good_trend,
    count(*) FILTER (WHERE flag_pacing_fast) AS n_pacing_fast,
    count(*) FILTER (WHERE flag_stale_review) AS n_stale_review,
    count(*) FILTER (WHERE flag_new OR flag_bad_trend OR flag_good_trend OR flag_pacing_fast OR flag_stale_review) AS n_flagged_any,
    round(100.0 * count(*) FILTER (WHERE flag_new OR flag_bad_trend OR flag_good_trend OR flag_pacing_fast OR flag_stale_review) / count(*), 1) AS pct_flagged
FROM flagged
WHERE date IN (DATE '2026-06-10', DATE '2026-06-11', DATE '2026-06-12')
GROUP BY date
ORDER BY date;
