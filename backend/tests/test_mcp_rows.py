import json
from types import SimpleNamespace

from app.services.mcp_history import _rows


def test_clickhouse_mcp_column_and_row_payload_is_normalized():
    result = SimpleNamespace(content=[
        SimpleNamespace(text=json.dumps({
            "columns": ["requirement_id", "expected_value"],
            "rows": [["mug-position", "frame left"], ["required-line", "The drive leaves at six."]],
        }))
    ])
    assert _rows(result) == [
        {"requirement_id": "mug-position", "expected_value": "frame left"},
        {"requirement_id": "required-line", "expected_value": "The drive leaves at six."},
    ]
