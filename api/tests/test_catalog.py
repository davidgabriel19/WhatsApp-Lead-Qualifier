"""Tests for the catalog loader and formatter."""
import json
from pathlib import Path

from app.catalog import Catalog


def test_loads_items_from_json(tmp_path: Path) -> None:
    catalog_file = tmp_path / "catalog.json"
    catalog_file.write_text(
        json.dumps(
            [
                {"title": "Item A", "price": "10", "location": "City", "link": "https://x"},
                {"title": "Item B", "price": "20", "location": "City", "link": "https://y"},
            ]
        )
    )

    catalog = Catalog(str(catalog_file))
    assert catalog.size() == 2


def test_missing_file_is_handled_gracefully(tmp_path: Path) -> None:
    catalog = Catalog(str(tmp_path / "does-not-exist.json"))
    assert catalog.size() == 0
    assert catalog.format_for_prompt() == "(empty catalog)"


def test_invalid_json_is_handled_gracefully(tmp_path: Path) -> None:
    catalog_file = tmp_path / "bad.json"
    catalog_file.write_text("not valid json {")
    catalog = Catalog(str(catalog_file))
    assert catalog.size() == 0


def test_non_list_top_level_is_rejected(tmp_path: Path) -> None:
    catalog_file = tmp_path / "obj.json"
    catalog_file.write_text('{"foo": "bar"}')
    catalog = Catalog(str(catalog_file))
    assert catalog.size() == 0


def test_format_for_prompt_handles_english_keys(tmp_path: Path) -> None:
    catalog_file = tmp_path / "catalog.json"
    catalog_file.write_text(
        json.dumps([{"title": "Hello", "price": "$10", "location": "NYC", "link": "https://x"}])
    )
    catalog = Catalog(str(catalog_file))
    out = catalog.format_for_prompt()
    assert "Hello" in out
    assert "$10" in out
    assert "NYC" in out


def test_format_for_prompt_handles_portuguese_keys(tmp_path: Path) -> None:
    # Backward-compat: accepts the legacy Portuguese keys.
    catalog_file = tmp_path / "catalog.json"
    catalog_file.write_text(
        json.dumps([{"titulo": "Olá", "preco": "R$ 10", "cidade": "SP", "link": "https://x"}])
    )
    catalog = Catalog(str(catalog_file))
    out = catalog.format_for_prompt()
    assert "Olá" in out
    assert "R$ 10" in out
