-- Analytical views. Each answers one business question; Tableau / the HTML dashboard read from these.

-- Delivered orders with delivery metrics (single source of truth for logistics questions).
CREATE OR REPLACE VIEW v_delivered_orders AS
SELECT o.order_id, c.customer_state AS state, o.order_purchase_timestamp AS purchased_at,
       EXTRACT(EPOCH FROM (o.order_delivered_customer_date - o.order_purchase_timestamp)) / 86400.0 AS delivery_days,
       EXTRACT(EPOCH FROM (o.order_delivered_customer_date - o.order_estimated_delivery_date)) / 86400.0 AS days_vs_estimate,
       (o.order_delivered_customer_date > o.order_estimated_delivery_date) AS is_late
FROM orders o JOIN customers c USING (customer_id)
WHERE o.order_status = 'delivered' AND o.order_delivered_customer_date IS NOT NULL;

-- Q1. Revenue and delivery performance by customer state (the bottleneck map).
CREATE OR REPLACE VIEW v_state_performance AS
WITH revenue AS (
    SELECT c.customer_state AS state, COUNT(DISTINCT o.order_id) AS orders,
           SUM(oi.price) AS revenue, SUM(oi.freight_value) AS freight
    FROM orders o JOIN customers c USING (customer_id) JOIN order_items oi USING (order_id)
    WHERE o.order_status = 'delivered' GROUP BY c.customer_state
), logistics AS (
    SELECT state, AVG(delivery_days) AS avg_delivery_days, AVG(is_late::int) AS late_rate,
           PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY delivery_days) AS p90_delivery_days
    FROM v_delivered_orders GROUP BY state
)
SELECT r.state, r.orders, ROUND(r.revenue, 0) AS revenue, ROUND(r.freight / NULLIF(r.revenue, 0) * 100, 1) AS freight_pct_of_revenue,
       ROUND(l.avg_delivery_days::numeric, 1) AS avg_delivery_days, ROUND(l.p90_delivery_days::numeric, 1) AS p90_delivery_days,
       ROUND((l.late_rate * 100)::numeric, 1) AS late_pct,
       RANK() OVER (ORDER BY l.avg_delivery_days DESC) AS slowest_rank,
       ROUND(r.revenue / SUM(r.revenue) OVER () * 100, 1) AS revenue_share_pct
FROM revenue r JOIN logistics l USING (state);

-- Q2. Monthly revenue with month-over-month growth (window functions).
CREATE OR REPLACE VIEW v_monthly_revenue AS
WITH m AS (
    SELECT DATE_TRUNC('month', o.order_purchase_timestamp)::date AS month,
           COUNT(DISTINCT o.order_id) AS orders, SUM(oi.price) AS revenue
    FROM orders o JOIN order_items oi USING (order_id)
    WHERE o.order_status = 'delivered' GROUP BY 1
)
SELECT month, orders, ROUND(revenue, 0) AS revenue,
       ROUND((revenue / NULLIF(LAG(revenue) OVER (ORDER BY month), 0) - 1) * 100, 1) AS mom_growth_pct,
       ROUND(AVG(revenue) OVER (ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 0) AS revenue_3m_avg
FROM m WHERE month BETWEEN '2017-01-01' AND '2018-08-01' ORDER BY month;

-- Q3. Does lateness hurt reviews?
CREATE OR REPLACE VIEW v_review_vs_delay AS
WITH r AS (
    SELECT d.order_id, d.is_late, d.days_vs_estimate, AVG(rv.review_score) AS score
    FROM v_delivered_orders d JOIN order_reviews rv USING (order_id) GROUP BY d.order_id, d.is_late, d.days_vs_estimate
)
SELECT CASE WHEN days_vs_estimate <= -7 THEN '1. 7+ days early' WHEN days_vs_estimate <= 0 THEN '2. on time (0-7 days early)'
            WHEN days_vs_estimate <= 7 THEN '3. 1-7 days late' ELSE '4. 7+ days late' END AS delivery_bucket,
       COUNT(*) AS orders, ROUND(AVG(score)::numeric, 2) AS avg_review_score
FROM r GROUP BY 1 ORDER BY 1;

-- Q4. Top categories by revenue with running share (Pareto).
CREATE OR REPLACE VIEW v_category_pareto AS
WITH cat AS (
    SELECT COALESCE(t.product_category_name_english, p.product_category_name, 'unknown') AS category,
           SUM(oi.price) AS revenue, COUNT(*) AS items
    FROM order_items oi JOIN orders o USING (order_id) JOIN products p USING (product_id)
    LEFT JOIN category_translation t USING (product_category_name)
    WHERE o.order_status = 'delivered' GROUP BY 1
)
SELECT category, items, ROUND(revenue, 0) AS revenue,
       ROUND(SUM(revenue) OVER (ORDER BY revenue DESC) / SUM(revenue) OVER () * 100, 1) AS cumulative_share_pct
FROM cat ORDER BY revenue DESC LIMIT 15;

-- Q5. Sellers with the most late shipments (min 100 orders).
CREATE OR REPLACE VIEW v_seller_lateness AS
SELECT oi.seller_id, s.seller_state AS state, COUNT(DISTINCT o.order_id) AS orders,
       ROUND(AVG((o.order_delivered_carrier_date > oi.shipping_limit_date)::int) * 100, 1) AS late_to_carrier_pct
FROM order_items oi JOIN orders o USING (order_id) JOIN sellers s USING (seller_id)
WHERE o.order_status = 'delivered' AND o.order_delivered_carrier_date IS NOT NULL
GROUP BY oi.seller_id, s.seller_state HAVING COUNT(DISTINCT o.order_id) >= 100
ORDER BY late_to_carrier_pct DESC LIMIT 10;
