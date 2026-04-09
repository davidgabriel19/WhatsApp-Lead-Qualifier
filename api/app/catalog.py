"""
Catalog loader and prompt formatter.

The catalog is a JSON file whose entries are injected into the system
prompt so the model can recommend only items that actually exist.
The schema of each entry is free-form — the formatter below handles
missing keys gracefully.
"""
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class Catalog:
    """Loads items from a JSON file and formats them for prompt injection."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._items: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            logger.warning("Catalog file not found: %s", self._path)
            self._items = []
            return
        try:
            with self._path.open(encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                raise ValueError("Catalog file must contain a JSON array at the top level")
            self._items = data
            logger.info("Catalog loaded: %d items from %s", len(self._items), self._path)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error("Failed to load catalog %s: %s", self._path, exc)
            self._items = []

    @property
    def items(self) -> list[dict[str, Any]]:
        return self._items

    def size(self) -> int:
        return len(self._items)

    def format_for_prompt(self) -> str:
        """
        Format the catalog as plain text to be injected into the system
        prompt. Missing keys are handled gracefully so partial entries
        don't break the formatting.
        """
        if not self._items:
            return "(empty catalog)"

        lines = []
        for item in self._items:
            title = item.get("title") or item.get("titulo") or "untitled"
            price = item.get("price") or item.get("preco") or "price on request"
            location = item.get("location") or item.get("cidade") or ""
            link = item.get("link", "")
            lines.append(f"- {title} – {price} – {location} – {link}")
        return "\n".join(lines)
