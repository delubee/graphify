CREATE VIEW active_users AS
SELECT u.id, u.email
FROM users u
JOIN orders o ON o.user_id = u.id
WHERE o.placed_at > NOW() - INTERVAL '30 days';

CREATE MATERIALIZED VIEW daily_order_totals AS
SELECT DATE(placed_at) AS order_day, SUM(total_cents) AS total_cents
FROM orders
GROUP BY DATE(placed_at);
