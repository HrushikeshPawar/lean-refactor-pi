#!/usr/bin/env python3
"""Offline browser checks for the generated timing report; screenshots go to /tmp."""

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[3]
REPORT = ROOT / "docs/reports/V7_V8_TIMING_2026-10-18.html"
SCREENSHOTS = Path("/tmp/arena-run-timing-preview")
BROWSER = Path.home() / ".cache/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-linux64/chrome-headless-shell"


def main():
    SCREENSHOTS.mkdir(exist_ok=True)
    errors, network = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(BROWSER), headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 1050}, reduced_motion="reduce")
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: network.append(request.url) if request.url.startswith(("http:", "https:")) else None)
        page.goto(REPORT.as_uri(), wait_until="load")
        assert page.locator("#run-rows tr").count() == 66
        assert "6,111" in page.locator("#kpi-requests").inner_text()
        assert page.locator("svg.chart").count() >= 5
        page.screenshot(path=str(SCREENSHOTS / "desktop.png"))

        page.locator("#family-filter").select_option("v8c")
        assert page.locator("#run-rows tr").count() == 5, {
            "rows": page.locator("#run-rows tr").count(), "errors": errors,
            "family": page.locator("#family-filter").input_value(),
        }
        assert "439" in page.locator("#kpi-requests").inner_text()
        assert "38.5%" in page.locator("#headline-share").inner_text()
        page.locator("#run-search").fill("Core.InitsUpdatesComm")
        assert page.locator("#run-rows tr").count() == 1
        page.locator("#run-rows [data-run]").click()
        assert page.locator("#timeline-panel").is_visible()
        assert "Core.InitsUpdatesComm" in page.locator("#timeline-title").inner_text()
        assert page.locator("#timeline-chart rect.interval").count() > 10
        page.locator("#run-search").fill("")
        page.locator("#run-sort").select_option("after_last_trace_s:-1")
        assert "fiberwise" in page.locator("#run-rows tr").first.inner_text()
        page.locator("#v8c-panel").screenshot(path=str(SCREENSHOTS / "v8c.png"))
        page.locator("#run-search").fill("no-such-run-unique-query")
        assert "0 of 5" in page.locator("#table-count").inner_text()
        page.locator("#run-search").fill("")
        page.locator("#family-filter").select_option("all")
        assert page.locator("#run-rows tr").count() == 66

        page.set_viewport_size({"width": 390, "height": 844})
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(SCREENSHOTS / "mobile.png"))
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "mobile page overflows"
        page.locator("#family-filter").select_option("v8b")
        assert page.locator("#run-rows tr").count() == 4
        assert not errors, errors
        assert not network, network
        browser.close()
    print("PASS: desktop/mobile rendering, 66-run inventory, family filters, KPI updates, search, sorting, timeline, no JS errors or network requests")
    print(f"Screenshots: {SCREENSHOTS}")


if __name__ == "__main__":
    main()
