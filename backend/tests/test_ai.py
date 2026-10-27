import pytest

from app.ai import MetaAIClient


def test_decode_json_accepts_fenced_content() -> None:
    assert MetaAIClient._decode_json('```json\n{"ok": true}\n```') == {"ok": True}


def test_decode_json_rejects_array() -> None:
    with pytest.raises(ValueError):
        MetaAIClient._decode_json("[1, 2]")
