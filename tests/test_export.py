import importlib.util
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
