"""Tests for the SQL views, run against a real (embedded) PostgreSQL with a tiny hand-made dataset.

Four delivered orders, two states, one order per delivery bucket, so every expected value
below can be checked by hand.
"""
import os
import tempfile

import psycopg2
import pytest

pgserver = pytest.importorskip("pgserver")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FIXTURE = """
INSERT INTO customers VALUES ('c1','u1','1','a','SP'),('c2','u2','1','a','SP'),('c3','u3','2','b','RJ'),('c4','u4','2','b','RJ');
INSERT INTO orders (order_id, customer_id, order_status, order_purchase_timestamp,
                    order_delivered_customer_date, order_estimated_delivery_date) VALUES
 ('o1','c1','delivered','2017-03-01','2017-03-06','2017-03-20'),  -- 14 days early
 ('o2','c2','delivered','2017-03-01','2017-03-11','2017-03-12'),  -- 1 day early
 ('o3','c3','delivered','2017-03-01','2017-03-20','2017-03-15'),  -- 5 days late
 ('o4','c4','delivered','2017-03-01','2017-04-10','2017-03-20'),  -- 21 days late
 ('o5','c1','canceled', '2017-03-01', NULL, '2017-03-20');        -- must be ignored
INSERT INTO order_items (order_id, order_item_id, product_id, seller_id, price, freight_value) VALUES
 ('o1',1,'p1','s1',100,10),('o2',1,'p1','s1',100,10),('o3',1,'p1','s1',100,10),('o4',1,'p1','s1',100,10),('o5',1,'p1','s1',999,10);
INSERT INTO order_reviews (review_id, order_id, review_score) VALUES ('r1','o1',5),('r2','o2',4),('r3','o3',3),('r4','o4',1);
INSERT INTO products (product_id, product_category_name) VALUES ('p1','beleza');
INSERT INTO category_translation VALUES ('beleza','beauty');
"""


@pytest.fixture(scope="module")
def cur():
    srv = pgserver.get_server(tempfile.mkdtemp())
    conn = psycopg2.connect(srv.get_uri())
    conn.autocommit = True
    c = conn.cursor()
    c.execute(open(os.path.join(ROOT, "sql", "schema.sql")).read())
    c.execute(FIXTURE)
    c.execute(open(os.path.join(ROOT, "sql", "views.sql")).read())
    yield c
    conn.close()


def rows(cur, sql):
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def test_canceled_orders_are_excluded(cur):
    assert rows(cur, "select count(*) n from v_delivered_orders")[0]["n"] == 4


def test_review_score_by_delivery_bucket(cur):
    got = {r["delivery_bucket"][:1]: float(r["avg_review_score"]) for r in rows(cur, "select * from v_review_vs_delay")}
    assert got == {"1": 5.0, "2": 4.0, "3": 3.0, "4": 1.0}


def test_state_performance(cur):
    s = {r["state"]: r for r in rows(cur, "select * from v_state_performance")}
    assert float(s["SP"]["late_pct"]) == 0.0 and float(s["RJ"]["late_pct"]) == 100.0
    assert float(s["SP"]["revenue_share_pct"]) == 50.0
    assert float(s["SP"]["avg_delivery_days"]) == 7.5 and float(s["RJ"]["avg_delivery_days"]) == 29.5
    assert s["RJ"]["slowest_rank"] == 1


def test_monthly_revenue_and_growth(cur):
    r = rows(cur, "select * from v_monthly_revenue")
    assert len(r) == 1 and r[0]["orders"] == 4 and float(r[0]["revenue"]) == 400.0
    assert r[0]["mom_growth_pct"] is None  # first month has no previous month


def test_category_pareto_uses_english_names(cur):
    r = rows(cur, "select * from v_category_pareto")
    assert r[0]["category"] == "beauty" and float(r[0]["cumulative_share_pct"]) == 100.0
