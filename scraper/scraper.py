"""
Generic catalog scraper.

Extracts listing data from paginated listing sites and dumps it as a JSON
file that can be fed straight into the `api/` service as a catalog.

The scraper is driven by a YAML config file — it has NO site-specific code
baked in. Point it at a new site by writing a new config; no Python edits
needed. See `config.example.yaml` for a documented template.

Usage:
    python scraper.py --config config.yaml --output output/catalog.json

Requirements:
    playwright, pyyaml
    (install browsers once: `python -m playwright install chromium`)
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import yaml
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("scraper")


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------


@dataclass
class FieldSelector:
    """One named field to extract from a page or card."""

    # CSS selectors tried in order; the first non-empty result wins.
    css: list[str] = field(default_factory=list)
    # Fallback regex applied to the element's / page's inner text if no CSS hit.
    regex: str | None = None
    # Optional post-processing: "int" | "float" | "clean_number" | None
    cast: str | None = None
    default: str = "N/A"


@dataclass
class TargetConfig:
    """One listing page to scrape."""

    name: str
    url: str


@dataclass
class ScraperConfig:
    """Full scraper configuration."""

    base_url: str
    targets: list[TargetConfig]

    # Selectors for the listing page ("cards")
    card_selectors: list[str]
    # Selectors for following through to a detail page, if any
    detail_link_selectors: list[str]
    # How the scraper recognizes itself has reached the full listing
    scroll_max_attempts: int = 10
    scroll_wait_ms: int = 4000
    load_more_selectors: list[str] = field(default_factory=list)

    # Cookie consent buttons to dismiss if they appear
    cookie_consent_selectors: list[str] = field(default_factory=list)

    # Fields to extract. Keys become the JSON keys in the output.
    card_fields: dict[str, FieldSelector] = field(default_factory=dict)
    detail_fields: dict[str, FieldSelector] = field(default_factory=dict)

    # Request timing
    page_timeout_ms: int = 60_000
    nav_timeout_ms: int = 90_000
    delay_between_items_seconds: float = 1.0
    delay_between_targets_seconds: float = 3.0

    # Browser behavior
    headless: bool = True
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )


def _load_field_selectors(raw: dict[str, Any] | None) -> dict[str, FieldSelector]:
    if not raw:
        return {}
    out = {}
    for key, value in raw.items():
        if isinstance(value, str):
            out[key] = FieldSelector(css=[value])
        elif isinstance(value, list):
            out[key] = FieldSelector(css=list(value))
        elif isinstance(value, dict):
            out[key] = FieldSelector(
                css=value.get("css", []) or [],
                regex=value.get("regex"),
                cast=value.get("cast"),
                default=value.get("default", "N/A"),
            )
        else:
            raise ValueError(f"Unsupported field selector spec for '{key}': {value!r}")
    return out


def load_config(path: Path) -> ScraperConfig:
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    targets = [TargetConfig(name=t["name"], url=t["url"]) for t in raw["targets"]]

    return ScraperConfig(
        base_url=raw["base_url"],
        targets=targets,
        card_selectors=raw.get("card_selectors", []),
        detail_link_selectors=raw.get("detail_link_selectors", []),
        scroll_max_attempts=raw.get("scroll_max_attempts", 10),
        scroll_wait_ms=raw.get("scroll_wait_ms", 4000),
        load_more_selectors=raw.get("load_more_selectors", []),
        cookie_consent_selectors=raw.get("cookie_consent_selectors", []),
        card_fields=_load_field_selectors(raw.get("card_fields")),
        detail_fields=_load_field_selectors(raw.get("detail_fields")),
        page_timeout_ms=raw.get("page_timeout_ms", 60_000),
        nav_timeout_ms=raw.get("nav_timeout_ms", 90_000),
        delay_between_items_seconds=raw.get("delay_between_items_seconds", 1.0),
        delay_between_targets_seconds=raw.get("delay_between_targets_seconds", 3.0),
        headless=raw.get("headless", True),
        user_agent=raw.get("user_agent", ScraperConfig.user_agent),
    )


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------


def _cast_value(value: str, cast: str | None) -> Any:
    if cast is None or value == "N/A":
        return value
    try:
        if cast == "int":
            match = re.search(r"(\d+)", value)
            return int(match.group(1)) if match else value
        if cast == "float":
            match = re.search(r"([\d.,]+)", value)
            if not match:
                return value
            cleaned = match.group(1).replace(".", "").replace(",", ".")
            return float(cleaned)
        if cast == "clean_number":
            # Keep only digits, dots and commas — useful for prices.
            return re.sub(r"[^\d.,]", "", value).strip(".,")
    except (ValueError, AttributeError):
        return value
    return value


def extract_by_css(element: Any, selectors: list[str], default: str = "N/A") -> str:
    """Return the inner text of the first matching selector, or `default`."""
    for selector in selectors:
        try:
            el = element.query_selector(selector)
            if el:
                text = (el.inner_text() or "").strip().replace("\n", " ")
                if text:
                    return text
        except Exception:
            continue
    return default


def extract_by_regex(text: str, pattern: str, default: str = "N/A") -> str:
    if not text:
        return default
    try:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            return (match.group(1) if match.groups() else match.group(0)).strip()
    except re.error as exc:
        logger.warning("Invalid regex %r: %s", pattern, exc)
    return default


def extract_field(element: Any, spec: FieldSelector, fallback_text: str = "") -> Any:
    """Try CSS selectors first, then regex against the provided text."""
    value = extract_by_css(element, spec.css, default=spec.default)
    if value == spec.default and spec.regex:
        value = extract_by_regex(fallback_text, spec.regex, default=spec.default)
    return _cast_value(value, spec.cast)


# ---------------------------------------------------------------------------
# Page helpers
# ---------------------------------------------------------------------------


def dismiss_cookie_consent(page: Page, selectors: list[str]) -> None:
    for selector in selectors:
        try:
            button = page.query_selector(selector)
            if button and button.is_visible():
                logger.info("Dismissing cookie consent with selector %r", selector)
                button.click(timeout=5000)
                page.wait_for_timeout(1500)
                return
        except Exception as exc:
            logger.debug("Cookie consent selector %r failed: %s", selector, exc)


def load_full_listing(page: Page, config: ScraperConfig) -> None:
    """Scroll (and click 'load more' if available) until no new content appears."""
    last_height = page.evaluate("document.body.scrollHeight")
    no_change_streak = 0

    for attempt in range(config.scroll_max_attempts):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(config.scroll_wait_ms)
        new_height = page.evaluate("document.body.scrollHeight")

        if new_height == last_height:
            no_change_streak += 1

            # Try clicking a "load more" button if configured
            clicked = False
            for selector in config.load_more_selectors:
                try:
                    btn = page.query_selector(selector)
                    if btn and btn.is_visible() and btn.is_enabled():
                        logger.info("Clicking 'load more' button (%s)", selector)
                        btn.click(timeout=5000)
                        page.wait_for_timeout(config.scroll_wait_ms)
                        new_height = page.evaluate("document.body.scrollHeight")
                        clicked = True
                        break
                except Exception as exc:
                    logger.debug("Load-more selector %r failed: %s", selector, exc)

            if not clicked and no_change_streak >= 2:
                logger.info("No more content to load (attempt %d)", attempt + 1)
                return
        else:
            no_change_streak = 0

        last_height = new_height


def find_detail_url(card: Any, link_selectors: list[str], base_url: str) -> str | None:
    """Return the absolute URL of the detail page for a listing card."""
    # If the card itself is an <a>, use its href.
    try:
        tag_name = card.evaluate("el => el.tagName.toLowerCase()")
    except Exception:
        tag_name = ""

    link_el = card if tag_name == "a" else None
    if link_el is None:
        for selector in link_selectors:
            try:
                link_el = card.query_selector(selector)
                if link_el:
                    break
            except Exception:
                continue

    if link_el is None:
        return None

    try:
        href = link_el.get_attribute("href") or ""
    except Exception:
        return None

    if not href:
        return None
    if href.startswith("http"):
        return href
    return urljoin(base_url + "/", href.lstrip("/"))


# ---------------------------------------------------------------------------
# Core scraping logic
# ---------------------------------------------------------------------------


def scrape_detail_page(
    url: str, context: BrowserContext, config: ScraperConfig
) -> dict[str, Any]:
    """Open a detail page and extract detail_fields."""
    logger.info("  Fetching detail page: %s", url)
    result: dict[str, Any] = {}
    page: Page | None = None
    try:
        page = context.new_page()
        page.goto(url, timeout=config.nav_timeout_ms, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        body_text = page.inner_text("body") if config.detail_fields else ""
        for key, spec in config.detail_fields.items():
            result[key] = extract_field(page, spec, fallback_text=body_text)
    except Exception as exc:
        logger.warning("  Failed to scrape detail page %s: %s", url, exc)
    finally:
        if page is not None:
            try:
                page.close()
            except Exception:
                pass
    return result


def scrape_target(
    target: TargetConfig, context: BrowserContext, config: ScraperConfig
) -> list[dict[str, Any]]:
    """Scrape a single listing page (one target)."""
    logger.info("=== Scraping target: %s (%s) ===", target.name, target.url)
    results: list[dict[str, Any]] = []
    page: Page | None = None

    try:
        page = context.new_page()
        page.goto(target.url, timeout=config.nav_timeout_ms, wait_until="domcontentloaded")
        dismiss_cookie_consent(page, config.cookie_consent_selectors)
        load_full_listing(page, config)

        # Find card elements using the configured selectors.
        cards: list[Any] = []
        for selector in config.card_selectors:
            found = page.query_selector_all(selector)
            if found:
                logger.info("Found %d cards with selector %r", len(found), selector)
                cards = found
                break

        if not cards:
            logger.warning("No cards found on %s", target.url)
            return []

        seen_links: set[str] = set()

        for index, card in enumerate(cards, start=1):
            try:
                card_text = card.inner_text() or ""
            except Exception:
                card_text = ""

            # Extract card-level fields
            card_data: dict[str, Any] = {"target": target.name}
            for key, spec in config.card_fields.items():
                card_data[key] = extract_field(card, spec, fallback_text=card_text)

            # Follow through to detail page if configured
            detail_url = find_detail_url(card, config.detail_link_selectors, config.base_url)
            if detail_url:
                if detail_url in seen_links:
                    logger.debug("Skipping duplicate link: %s", detail_url)
                    continue
                seen_links.add(detail_url)
                card_data["link"] = detail_url

                if config.detail_fields:
                    detail_data = scrape_detail_page(detail_url, context, config)
                    # Detail values override card values only when non-default.
                    for key, value in detail_data.items():
                        if value and value != "N/A":
                            card_data[key] = value
                    time.sleep(config.delay_between_items_seconds)

            logger.info("  [%d/%d] %s", index, len(cards), card_data.get("title", detail_url or "?"))
            results.append(card_data)

    except Exception as exc:
        logger.exception("Error scraping target %s: %s", target.name, exc)
    finally:
        if page is not None:
            try:
                page.close()
            except Exception:
                pass

    return results


def run_scraper(config: ScraperConfig, output_path: Path) -> None:
    all_results: list[dict[str, Any]] = []

    with sync_playwright() as playwright:
        browser: Browser = playwright.chromium.launch(headless=config.headless)
        context = browser.new_context(
            user_agent=config.user_agent,
            java_script_enabled=True,
            ignore_https_errors=True,
        )
        context.set_default_navigation_timeout(config.nav_timeout_ms)
        context.set_default_timeout(config.page_timeout_ms)

        try:
            for target in config.targets:
                target_results = scrape_target(target, context, config)
                all_results.extend(target_results)
                logger.info(
                    "Target %s complete: %d items extracted", target.name, len(target_results)
                )
                time.sleep(config.delay_between_targets_seconds)
        finally:
            browser.close()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    logger.info("Wrote %d items to %s", len(all_results), output_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generic catalog scraper.")
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to the YAML config file describing the target site.",
    )
    parser.add_argument(
        "--output",
        default=Path("output/catalog.json"),
        type=Path,
        help="Where to write the resulting JSON catalog (default: output/catalog.json).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.config.exists():
        logger.error("Config file not found: %s", args.config)
        return 1

    config = load_config(args.config)
    run_scraper(config, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
