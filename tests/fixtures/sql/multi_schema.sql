SET search_path = analytics, public;

CREATE TABLE analytics.events (
    id INTEGER PRIMARY KEY,
    user_id INTEGER
);

SELECT user_id
FROM events;
