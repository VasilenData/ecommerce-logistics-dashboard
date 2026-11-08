import importlib.util
import csv
import io
from pathlib import Path

import pytest

pytest.importorskip("psycopg2")
pytest.importorskip("pandas")
spec = importlib.util.spec_from_file_location("logistics_pipeline", Path(__file__).resolve().parents[1] / "scripts/pipeline.py")
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


def test_failed_export_replacement_keeps_previous_file(tmp_path, monkeypatch):
    output = tmp_path / "data.json"
    output.write_text('{"previous":"complete"}', encoding="utf-8")

    def fail_replace(*args):
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(pipeline.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replacement failure"):
        pipeline.write_export('{"next":"complete"}', str(output))
    assert output.read_text(encoding="utf-8") == '{"previous":"complete"}'
    assert list(tmp_path.iterdir()) == [output]


class CopyCursor:
    def __init__(self, columns):
        self.columns = columns
        self.rows = None

    def execute(self, *args):
        pass

    def fetchall(self):
        return [(column,) for column in self.columns]

    def copy_expert(self, sql, stream):
        self.rows = list(csv.reader(io.StringIO(stream.read())))


@pytest.mark.parametrize("prefix", ["00001", "00123", "12345"])
def test_csv_load_preserves_text_identifiers_and_literal_na(tmp_path, prefix):
    source = tmp_path / "customers.csv"
    source.write_text("customer_id,customer_zip_code_prefix,customer_city\n00123," + prefix + ",NA\n", encoding="utf-8")
    cursor = CopyCursor(["customer_id", "customer_zip_code_prefix", "customer_city"])
    assert pipeline.copy_table(cursor, "customers", source) == 1
    assert cursor.rows == [["00123", prefix, "NA"]]


def test_product_nullable_integer_conversion_preserves_missing_values(tmp_path):
    source = tmp_path / "products.csv"
    source.write_text("product_id,product_category_name,product_weight_g\np1,NA,12.0\np2,,\n", encoding="utf-8")
    cursor = CopyCursor(["product_id", "product_category_name", "product_weight_g"])
    assert pipeline.copy_table(cursor, "products", source) == 2
    assert cursor.rows == [["p1", "NA", "12"], ["p2", "", ""]]
