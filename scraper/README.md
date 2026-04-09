# Scraper — WhatsApp Lead Qualifier

Generic, config-driven scraper that turns a paginated listing site into a
JSON catalog consumable by the [`api/`](../api/) service.

This directory is one of three components of the broader
[`whatsapp-lead-qualifier`](../README.md) project.

## Why this exists

The qualifier API needs a catalog of real items to recommend — properties,
products, courses, whatever matches your domain. Most businesses already
publish that catalog on a public website. This scraper bridges the gap:
point it at the site, describe the selectors in a YAML file, and it
produces a JSON file ready to drop into `api/data/`.

## Features

- **Zero site-specific code.** All selectors live in a YAML config.
  Scraping a new site means writing a new config, not editing Python.
- **Two-level extraction**: fields from the listing card itself plus
  optional fields fetched from each item's detail page.
- **Robust selectors**: each field accepts a list of CSS selectors
  (first match wins) and an optional regex fallback applied to the
  element text.
- **Value casting**: `int`, `float`, and `clean_number` casts keep the
  output tidy out of the box.
- **Infinite-scroll and click-to-paginate** supported transparently.
- **Cookie-consent dismissal** with a configurable list of button
  selectors.

## Quick start

### 1. Install

```bash
cd scraper
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
```

### 2. Write a config

Copy the template and edit the selectors to match your target site:

```bash
cp config.example.yaml my-site.yaml
# Edit my-site.yaml — see the inline comments for guidance
```

### 3. Run

```bash
python scraper.py --config my-site.yaml --output output/catalog.json
```

The resulting JSON has this shape (keys depend on your `card_fields`
and `detail_fields`):

```json
[
  {
    "target": "category-one-cityA",
    "title": "Sample listing",
    "price": "1200.00",
    "code": "ABC123",
    "link": "https://example.com/item/123",
    "description": "...",
    "size": 120,
    "location": "City, State"
  }
]
```

### 4. Feed it into the API

```bash
cp output/catalog.json ../api/data/catalog.json
# In api/.env set:
#   CATALOG_PATH=data/catalog.json
```

Restart the API and the new catalog is live.

## Writing a config

The config is a single YAML file with three main parts:

1. **Targets** — one entry per listing page you want to scrape. Each
   target gets tagged with its `name` in the output, so you can mix
   categories, cities, or filters and tell them apart later.

2. **Card selectors** — how to find each listing on the page. The
   scraper tries each selector in order and uses the first that
   yields results, so list them from most to least specific.

3. **Field selectors** — what to extract from each card (and
   optionally each detail page). A field can be a single CSS
   selector, a list of selectors, or a full object with CSS + regex
   fallback + value cast.

See [`config.example.yaml`](config.example.yaml) for a fully commented
example.

### Field selector shapes

```yaml
# Shape 1 — single selector
title: 'h2.title'

# Shape 2 — list of selectors, first match wins
title:
  - 'h2.title'
  - '.card-title'
  - '.listing-title'

# Shape 3 — full object with regex fallback and cast
price:
  css:
    - '.price'
    - '[class*="value"]'
  regex: '\$\s*([\d.,]+)'
  cast: clean_number
  default: 'N/A'
```

Supported cast values: `int`, `float`, `clean_number` (strips
everything except digits, dots and commas — useful for prices).

## Legal and ethical notes

- **Check `robots.txt`** and the site's terms of service before
  scraping. Not every site allows automated access.
- **Be a good citizen**: keep `delay_between_items_seconds` and
  `delay_between_targets_seconds` at reasonable values so you don't
  hammer the origin.
- **Don't republish data you don't own**. This tool is intended for
  scraping your own site, sites you have permission to scrape, or
  public data where republication is allowed.
- The `headless: true` default and realistic user agent are there to
  work with modern JS-heavy sites — not to evade anti-bot measures.
  If a site explicitly blocks scraping, respect the signal.

## Troubleshooting

**"No cards found on ..."** — your `card_selectors` don't match the
DOM. Open the site in a browser, right-click a card, choose "Copy
selector", paste it into the config, and iterate.

**Fields all come back as `N/A`** — the CSS selectors for those fields
don't match what's inside the card element. Remember that each
selector is scoped to its parent (card selectors to the page, field
selectors to the card). If a field lives outside the card on the
listing page, move it to `detail_fields` instead.

**The scraper hangs** — some sites open modals that block content.
Add their close-button selectors to `cookie_consent_selectors` — the
name is historical; anything there gets clicked if visible.

**Output is missing half the listings** — the site probably paginates
via click rather than scroll. Add the "next page" or "load more"
selector to `load_more_selectors`.
