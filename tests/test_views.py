"""Tests for the SQL views, run against a real (embedded) PostgreSQL with a tiny hand-made dataset.

Four delivered orders, two states, one order per delivery bucket, so every expected value
below can be checked by hand.
"""
import os
import tempfile
import uuid

import pytest

psycopg2 = pytest.importorskip("psycopg2")
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
def database_dsn():
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pgserver = pytest.importorskip("pgserver")
        dsn = pgserver.get_server(tempfile.mkdtemp()).get_uri()
    return dsn


@pytest.fixture(scope="module")
def cur(database_dsn):
    conn = psycopg2.connect(database_dsn)
    conn.autocommit = True
    c = conn.cursor()
    schema = "logistics_test_" + uuid.uuid4().hex
    c.execute(f'CREATE SCHEMA "{schema}"')
    c.execute(f'SET search_path TO "{schema}"')
    c.execute(open(os.path.join(ROOT, "sql", "schema.sql")).read())
    c.execute(FIXTURE)
    c.execute(open(os.path.join(ROOT, "sql", "views.sql")).read())
    yield c
    c.execute(f'DROP SCHEMA "{schema}" CASCADE')
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


def test_unknown_delivery_estimate_is_not_classified_as_late(cur):
    cur.execute("BEGIN")
    try:
        cur.execute("INSERT INTO orders (order_id,customer_id,order_status,order_purchase_timestamp,"
                    "order_delivered_customer_date) VALUES ('unknown-estimate','c1','delivered','2017-03-01','2017-03-20')")
        cur.execute("INSERT INTO order_reviews (review_id,order_id,review_score) VALUES ('unknown','unknown-estimate',1)")
        assert sum(row["orders"] for row in rows(cur, "select * from v_review_vs_delay")) == 4
        assert rows(cur, "select count(*) n from v_delivered_orders")[0]["n"] == 5
    finally:
        cur.execute("ROLLBACK")


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


def test_seller_late_rate_counts_orders_once_even_with_multiple_items(cur):
    cur.execute("BEGIN")
    try:
        cur.execute("insert into sellers(seller_id, seller_state) values ('fixture-seller', 'SP')")
        cur.execute("""insert into orders(order_id, customer_id, order_status, order_purchase_timestamp,
                       order_delivered_carrier_date)
                       select 'seller-test-' || n, 'c1', 'delivered', '2017-03-01'::timestamp, '2017-03-02'::timestamp
                       from generate_series(1, 100) n""")
        cur.execute("""insert into order_items(order_id, order_item_id, product_id, seller_id,
                       shipping_limit_date, price, freight_value)
                       select 'seller-test-' || n, item, 'p1', 'fixture-seller',
                              case when n = 1 then '2017-03-01'::timestamp else '2017-03-03'::timestamp end, 10, 1
                       from generate_series(1, 100) n,
                            lateral generate_series(1, case when n = 1 then 10 else 1 end) item""")
        result = rows(cur, "select orders, late_to_carrier_pct from v_seller_lateness where seller_id='fixture-seller'")[0]
        assert result["orders"] == 100
        assert float(result["late_to_carrier_pct"]) == 1.0
    finally:
        cur.execute("ROLLBACK")


def test_failed_csv_rebuild_preserves_previous_database_and_export(cur, database_dsn, tmp_path):
    from scripts.pipeline import run

    cur.execute("select current_schema()")
    schema = cur.fetchone()[0]
    # connection.dsn masks its password; reconnect using the original fixture DSN.
    dsn = psycopg2.extensions.make_dsn(database_dsn, options=f"-c search_path={schema}")
    output = tmp_path / "data.json"
    output.write_text('{"previous":"complete"}', encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        run(str(tmp_path), dsn, str(output))
    assert rows(cur, "select count(*) n from orders")[0]["n"] == 5
    assert rows(cur, "select count(*) n from v_delivered_orders")[0]["n"] == 4
    assert output.read_text(encoding="utf-8") == '{"previous":"complete"}'



def test_monthly_growth_and_average_include_zero_sale_calendar_month(cur):
    cur.execute("BEGIN")
    try:
        cur.execute("INSERT INTO orders(order_id,customer_id,order_status,order_purchase_timestamp) "
                    "VALUES ('may-order','c1','delivered','2017-05-01')")
        cur.execute("INSERT INTO order_items(order_id,order_item_id,price,freight_value) "
                    "VALUES ('may-order',1,200,0)")
        result = rows(cur, "select * from v_monthly_revenue order by month")
        assert [row["month"].month for row in result] == [3, 4, 5]
        assert [float(row["revenue"]) for row in result] == [400, 0, 200]
        assert [row["orders"] for row in result] == [4, 0, 1]
        assert result[0]["mom_growth_pct"] is None
        assert float(result[1]["mom_growth_pct"]) == -100
        assert result[2]["mom_growth_pct"] is None  # zero denominator, not March's revenue
        assert float(result[2]["revenue_3m_avg"]) == 200  # (400 + 0 + 200) / 3
        assert sum(float(row["revenue"]) for row in result) == 600
    finally:
        cur.execute("ROLLBACK")


def test_monthly_revenue_empty_input_remains_empty(cur):
    cur.execute("BEGIN")
    try:
        cur.execute("UPDATE orders SET order_status='canceled'")
        assert rows(cur, "select * from v_monthly_revenue") == []
    finally:
        cur.execute("ROLLBACK")
