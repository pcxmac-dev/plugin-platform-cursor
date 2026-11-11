"""The weekly check (CI's schedule, LIMINAL_VENDOR_PAGES=1): Cursor's public pages read again, each written-in figure
looked for (verify.check_sources); and every model's prices (at standard speed, at Fast speed, Grok 4.7's long
context) and every plan's price compared with the tables row by row. A figure gone or changed means the table is
stale and the plugin needs a release; the failure names the model or the plan. And every address on the plugin's
cards (apis.py) asked once. Nothing is read on a push or a pull request."""
from __future__ import annotations

import os
import re

import pytest

from liminal_libs.assistants.verify import check_sources, page_text
from plugin_platform_cursor import ASSISTANT, FAST, LEGACY, LEGACY_PAGE, LONG_CONTEXT, MODELS, PRICING, SUBSCRIPTION

pytestmark = pytest.mark.skipif(not os.environ.get("LIMINAL_VENDOR_PAGES"),
                                reason="LIMINAL_VENDOR_PAGES=1 reads the vendor's pages (the weekly CI run)")

AMOUNT = r"\$(\d[\d,]*(?:\.\d+)?)"


def plain(url: str) -> str:
    """A page's text, a markdown table's pipes and escapes taken out (the page may be served either way)."""
    return re.sub(r"\s+", " ", page_text(url).replace("|", " ").replace("\\$", "$")).strip()


def prices(text: str, title: str) -> tuple[float, ...] | None:
    """A price row's figures after its title: input, cache write ("-": none), cache read, output, per million tokens."""
    row = re.search(re.escape(title) + rf" {AMOUNT} (-|{AMOUNT}) {AMOUNT} {AMOUNT}", text)
    if row is None:
        return None
    figures = [row.group(1), row.group(4), row.group(5)]
    return tuple(float(f.replace(",", "")) for f in figures)


def test_the_tables_still_match_cursors_pages():
    problems = check_sources(ASSISTANT)
    assert problems == [], "\n".join(problems)


def test_every_models_prices_are_still_the_pricing_pages():
    text = plain(PRICING)
    wrong = []
    for m in MODELS:
        rows = {"standard": (prices(text, m.title), (m.input_usd, m.cached_usd, m.output_usd)),
                "Fast": (prices(text, f"{m.title} (Fast)"), FAST[m.id])}
        if m.id in LONG_CONTEXT:
            standard, fast = LONG_CONTEXT[m.id]
            rows["500k"] = (prices(text, f"{m.title} 500k"), standard)
            rows["500k Fast"] = (prices(text, f"{m.title} 500k (Fast)"), fast)
        for speed, (page, mine) in rows.items():
            if page is None:
                wrong.append(f"{m.title} ({m.id}), {speed}: no longer on the pricing page")
            elif page != mine:
                wrong.append(f"{m.title} ({m.id}), {speed}: the page's {page} (input, cached input, output a million "
                             f"tokens), the table's {mine}")
    assert wrong == [], "the table is stale:\n" + "\n".join(wrong)


def test_every_plans_price_is_still_the_pages():
    text, legacy = plain(PRICING), plain(LEGACY_PAGE)
    wrong = []
    if not re.search(r"Free \$0 Limited", text):
        wrong.append("Free: no longer $0 with limited usage")
    for name, (month, year, usage) in SUBSCRIPTION.items():
        title = ASSISTANT.plan_of(name).title
        if not re.search(rf"{re.escape(title)} \${month:,}/mo {re.escape(usage)}", text):
            wrong.append(f"{title}: no longer ${month}/mo with {usage} usage")
        if f"${year:,}/yr for {title}" not in text:
            wrong.append(f"{title}: no longer ${year:,}/yr")
    for name, month in LEGACY.items():
        title = ASSISTANT.plan_of(name).title.replace(" (legacy)", "")
        if not re.search(rf"{re.escape(title)} \${month}/mo", legacy):
            wrong.append(f"{title} (legacy): no longer ${month}/mo")
    assert wrong == [], "the table is stale:\n" + "\n".join(wrong)


def test_every_address_on_the_cards_answers():
    """Each address on the cards asked once (sources.apis.dead_links)."""
    from liminal_libs.sources.apis import dead_links
    from plugin_platform_cursor.apis import APIS

    assert dead_links(APIS) == []
