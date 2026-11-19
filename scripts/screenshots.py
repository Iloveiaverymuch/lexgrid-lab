"""Capture README screenshots from a running `lexgrid serve` (real indexes and models).

Usage (server running with LEXGRID_API_KEYS="dev-fr:FR;dev-all:EU,FR,DE"):
    uv run --with playwright python scripts/screenshots.py            # uses the installed Google Chrome
    uv run --with playwright python scripts/screenshots.py --chromium # after `playwright install chromium`
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any

OUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots"


async def capture(base: str, use_chromium: bool, timeout_s: int) -> list[Path]:
    from playwright.async_api import async_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    async with async_playwright() as p:
        browser = await (p.chromium.launch() if use_chromium else p.chromium.launch(channel="chrome"))
        page = await browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1.5)
        page.set_default_timeout(timeout_s * 1000)

        async def shot(name: str, full_page: bool = False) -> None:
            path = OUT / f"{name}.png"
            await page.screenshot(path=str(path), full_page=full_page)
            saved.append(path)
            print(f"saved {path.relative_to(OUT.parents[1])}")

        async def connect(key: str) -> None:
            await page.fill("#key", key)
            await page.click("#keyform button")
            await page.wait_for_function("document.getElementById('scope').textContent.startsWith('Can search')")

        async def tab(view: str) -> None:
            await page.click(f"nav.tabs button[data-view={view}]")

        async def mode(m: str) -> None:
            await page.click(f"#modegroup button[data-mode={m}]")

        async def search_done() -> None:
            await page.wait_for_timeout(200)
            await page.wait_for_function("!document.getElementById('searchbtn').disabled")

        async def jurisdictions(*wanted: str) -> None:
            for j in ("EU", "FR", "DE"):
                btn = page.locator(f"#jurgroup button.jur.{j}")
                pressed = await btn.get_attribute("aria-pressed") == "true"
                if pressed != (j in wanted):
                    await btn.click()

        async def search(query: str) -> None:
            await page.fill("#q", query)
            await page.click("#searchbtn")
            await search_done()

        async def hover(key: str) -> Any:
            row = page.locator(f'.compare li[data-key="{key}"]')
            if await row.count():  # the article may be absent from every top 10: then no highlight
                await row.first.hover()
                await page.wait_for_timeout(150)
            else:
                print(f"note: {key} not in any column, screenshot without highlight")

        await page.goto(base)
        await connect("dev-all")

        # Warm up the models so the screenshots show steady-state timings.
        await mode("hybrid_rrf_rerank")
        await jurisdictions("FR")
        await search("délai de rétractation")

        await mode("hybrid_rrf")
        await page.click('#searchpresets button:has-text("Article number")')
        await search_done()
        await shot("01-search-article-number")

        await page.locator('#searchout button:has-text("Trace source")').first.click()
        await page.wait_for_selector(".chain")
        await shot("02-lineage")
        await page.keyboard.press("Escape")

        await mode("compare")
        await jurisdictions("FR")
        await search("combien de jours a le consommateur pour se rétracter après un achat en ligne ?")
        await hover("FR:C. conso:L221-18")
        await shot("03-compare-four-rankings")

        await page.click('#searchpresets button:has-text("French question, German law")')
        await search_done()
        await hover("DE:BGB:357")
        await shot("04-cross-lingual-weakness")

        await mode("hybrid_rrf_rerank")
        await page.click('#searchpresets button:has-text("Three countries")')
        await search_done()
        await shot("05-three-countries")

        await tab("ask")
        await page.click('#askpresets button:has-text("Withdrawal period")')
        await page.wait_for_selector(".answer, .notice")
        await shot("06-ask-cited-answer")
        await page.click('#askpresets button:has-text("Not in the corpus")')
        await page.wait_for_timeout(300)
        await page.wait_for_function("!document.getElementById('askbtn').disabled")
        await shot("07-ask-abstains")

        await tab("indexes")
        await page.wait_for_selector(".jblock")
        await shot("08-index-history-and-gate", full_page=True)

        await tab("evaluation")
        await page.evaluate(
            """() => { const s = document.getElementById('runsel');
                 const i = [...s.options].findIndex(o => o.text.startsWith('D4-EVAL-DIVERSIFY-01'));
                 if (i >= 0) { s.value = String(i); s.dispatchEvent(new Event('change')); } }"""
        )
        await shot("09-evaluation", full_page=True)

        await tab("search")
        await connect("dev-fr")
        await page.click('#searchpresets button:has-text("Outside your scope")')
        await page.wait_for_selector(".notice")
        await shot("10-scope-refused")

        await browser.close()
    return saved


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000/")
    ap.add_argument("--chromium", action="store_true", help="use Playwright's Chromium instead of Google Chrome")
    ap.add_argument("--timeout", type=int, default=90, help="seconds per step (first rerank loads the model)")
    args = ap.parse_args()
    asyncio.run(capture(args.base, args.chromium, args.timeout))


if __name__ == "__main__":
    main()
