"""
Tests for the QualifierService with a mocked AI client and handoff.

These tests exercise the full flow without ever touching the OpenAI API.
"""
import json
from pathlib import Path
from typing import Any

import pytest

from app.catalog import Catalog
from app.services.qualifier import QualifierService
from app.session_store import SessionStore


class FakeAIClient:
    """Stub AI client that returns a scripted list of replies."""

    def __init__(self, scripted_replies: list[str]) -> None:
        self._replies = list(scripted_replies)
        self.calls: list[list[dict[str, Any]]] = []

    def chat(self, messages: list[dict[str, Any]], max_tokens: int) -> str:
        self.calls.append(messages)
        if not self._replies:
            raise RuntimeError("FakeAIClient ran out of scripted replies")
        return self._replies.pop(0)


class FakeHandoff:
    """Stub handoff client that just records dispatches."""

    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled
        self.dispatched: list[tuple[str, str]] = []

    def is_enabled(self) -> bool:
        return self._enabled

    def dispatch(self, user_id: str, summary: str) -> None:
        self.dispatched.append((user_id, summary))


@pytest.fixture
def prompts_dir(tmp_path: Path) -> Path:
    system = tmp_path / "system.md"
    system.write_text("You are a test assistant.")
    summary = tmp_path / "summary.md"
    summary.write_text("Summarize the conversation.")
    return tmp_path


@pytest.fixture
def catalog_path(tmp_path: Path) -> str:
    f = tmp_path / "catalog.json"
    f.write_text(
        json.dumps(
            [{"title": "Item A", "price": "$10", "location": "City", "link": "https://x"}]
        )
    )
    return str(f)


def make_service(
    ai_replies: list[str],
    prompts_dir: Path,
    catalog_path: str,
    handoff_enabled: bool = True,
) -> tuple[QualifierService, FakeAIClient, FakeHandoff]:
    ai = FakeAIClient(ai_replies)
    handoff = FakeHandoff(enabled=handoff_enabled)
    service = QualifierService(
        ai_client=ai,  # type: ignore[arg-type]
        session_store=SessionStore(ttl_minutes=10),
        catalog=Catalog(catalog_path),
        handoff=handoff,  # type: ignore[arg-type]
        system_prompt_path=str(prompts_dir / "system.md"),
        summary_prompt_path=str(prompts_dir / "summary.md"),
        qualified_lead_tag="#qualified_lead",
        max_tokens_chat=100,
        max_tokens_summary=100,
    )
    return service, ai, handoff


def test_regular_message_returns_reply_without_handoff(
    prompts_dir: Path, catalog_path: str
) -> None:
    service, ai, handoff = make_service(
        ["Sure, happy to help! What are you looking for?"],
        prompts_dir,
        catalog_path,
    )

    reply, is_qualified = service.process_message("user1", "Hi")

    assert "happy to help" in reply
    assert is_qualified is False
    assert len(ai.calls) == 1


def test_qualified_lead_tag_strips_and_signals_handoff(
    prompts_dir: Path, catalog_path: str
) -> None:
    service, _, handoff = make_service(
        ["Great, a specialist will be in touch. Thanks! #qualified_lead"],
        prompts_dir,
        catalog_path,
    )

    reply, is_qualified = service.process_message("user1", "I want to buy")

    assert is_qualified is True
    assert "#qualified_lead" not in reply
    assert "a specialist" in reply


def test_conversation_history_persists_across_messages(
    prompts_dir: Path, catalog_path: str
) -> None:
    service, ai, _ = make_service(
        ["First reply", "Second reply"],
        prompts_dir,
        catalog_path,
    )

    service.process_message("user1", "first question")
    service.process_message("user1", "second question")

    history = service.sessions.get_history("user1")
    # 2 user messages + 2 assistant replies
    assert len(history) == 4
    assert history[0] == {"role": "user", "content": "first question"}
    assert history[1] == {"role": "assistant", "content": "First reply"}
    assert history[2] == {"role": "user", "content": "second question"}
    assert history[3] == {"role": "assistant", "content": "Second reply"}


def test_reset_user_clears_history(prompts_dir: Path, catalog_path: str) -> None:
    service, _, _ = make_service(["ok"], prompts_dir, catalog_path)
    service.process_message("user1", "hello")
    service.reset_user("user1")
    assert service.sessions.get_history("user1") == []


def test_generate_and_dispatch_handoff_calls_handoff_client(
    prompts_dir: Path, catalog_path: str
) -> None:
    service, _, handoff = make_service(
        ["Reply with #qualified_lead", "Generated summary here"],
        prompts_dir,
        catalog_path,
    )

    service.process_message("user1", "I want to buy")
    service.generate_and_dispatch_handoff("user1")

    assert len(handoff.dispatched) == 1
    assert handoff.dispatched[0][0] == "user1"
    assert "summary" in handoff.dispatched[0][1].lower()


def test_disabled_handoff_is_skipped(prompts_dir: Path, catalog_path: str) -> None:
    service, _, handoff = make_service(
        ["Reply #qualified_lead"],
        prompts_dir,
        catalog_path,
        handoff_enabled=False,
    )

    service.process_message("user1", "I want to buy")
    service.generate_and_dispatch_handoff("user1")

    assert handoff.dispatched == []


def test_tag_detection_is_whitespace_tolerant(
    prompts_dir: Path, catalog_path: str
) -> None:
    service, _, _ = make_service(
        ["Thanks! # qualified_lead"],  # stray space inside the tag
        prompts_dir,
        catalog_path,
    )
    _, is_qualified = service.process_message("user1", "done")
    assert is_qualified is True
