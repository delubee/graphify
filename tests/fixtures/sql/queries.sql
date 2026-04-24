WITH recent_orders AS (
    SELECT user_id, SUM(total_cents) AS spend
    FROM orders
    WHERE placed_at > NOW() - INTERVAL '30 days'
    GROUP BY user_id
)
SELECT u.email, r.spend
FROM users u
JOIN recent_orders r ON r.user_id = u.id
ORDER BY r.spend DESC
LIMIT 10;

INSERT INTO audit_log (table_name, event) VALUES ('orders', 'monthly_report_run');
