"""Load the Olist CSVs into PostgreSQL, build the analytical views, export docs/data.json for the dashboard.

Usage:
  python scripts/pipeline.py --data-dir data                      # embedded local Postgres (pgserver), no setup
  python scripts/pipeline.py --data-dir data --dsn postgresql://user:pw@localhost/ecommerce
"""
import argparse
import io
import json
import os
import tempfile
from datetime import date, datetime
from decimal import Decimal

import pandas as pd
import psycopg2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TABLES = {  # table -> csv
    "customers": "olist_customers_dataset.csv", "sellers": "olist_sellers_dataset.csv",
    "category_translation": "product_category_name_translation.csv", "products": "olist_products_dataset.csv",
    "orders": "olist_orders_dataset.csv", "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv", "order_reviews": "olist_order_reviews_dataset.csv",
}
VIEWS = ["v_state_performance", "v_monthly_revenue", "v_review_vs_delay", "v_category_pareto", "v_seller_lateness"]


def copy_table(cur, table, path):
    df = pd.read_csv(path)
    if table == "order_reviews":  # review_id is not unique in the source
        df = df.drop_duplicates()
    cur.execute("select column_name from information_schema.columns where table_schema=current_schema() "
                "and table_name=%s order by ordinal_position", (table,))
    cols = [r[0] for r in cur.fetchall()]
    df = df[cols]
    if table == 'products':  # pandas reads nullable ints as floats
        for c in cols[2:]: df[c] = df[c].astype('Int64')
    buf = io.StringIO(); df.to_csv(buf, index=False, header=False); buf.seek(0)
    cur.copy_expert(f"COPY {table} ({','.join(cols)}) FROM STDIN WITH (FORMAT csv, NULL '')", buf)
    return len(df)


def jsonable(v):
    if isinstance(v, Decimal): return float(v)
    if isinstance(v, (date, datetime)): return v.isoformat()
    return v


def write_export(payload, path):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False) as stream:
            temporary = stream.name
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)


def run(data_dir, dsn, out_path=None):
    conn = psycopg2.connect(dsn)
    try:
        # DDL, loads and views share one transaction. A bad CSV must not leave
        # yesterday's tables dropped or partially replaced.
        with conn:
            with conn.cursor() as cur:
                with open(os.path.join(ROOT, "sql", "schema.sql"), encoding="utf-8") as source:
                    cur.execute(source.read())
                counts = {t: copy_table(cur, t, os.path.join(data_dir, f)) for t, f in TABLES.items()}
                print("loaded", counts)
                with open(os.path.join(ROOT, "sql", "views.sql"), encoding="utf-8") as source:
                    cur.execute(source.read())
                out = {"row_counts": counts}
                cur.execute("select count(*), coalesce(sum(price), 0) from order_items"); n, rev = cur.fetchone()
                out["totals"] = {"order_items": n, "gross_item_revenue": float(rev)}
                cur.execute("select count(*) from orders"); out["totals"]["orders"] = cur.fetchone()[0]
                for v in VIEWS:
                    cur.execute(f"select * from {v}"); cols = [c[0] for c in cur.description]
                    out[v] = [{c: jsonable(x) for c, x in zip(cols, row)} for row in cur.fetchall()]
                    print(v, len(out[v]), "rows")
                payload = json.dumps(out, indent=1, allow_nan=False)
    finally:
        conn.close()
    write_export(payload, out_path or os.path.join(ROOT, "docs", "data.json"))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--data-dir", default=os.path.join(ROOT, "data")); ap.add_argument("--dsn")
    a = ap.parse_args()
    if a.dsn: run(a.data_dir, a.dsn)
    else:
        import pgserver
        srv = pgserver.get_server(tempfile.mkdtemp()); run(a.data_dir, srv.get_uri())
