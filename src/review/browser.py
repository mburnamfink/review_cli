"""Headless-Chrome edge for sites behind a JS/WAF bot-challenge.

Plain ``httpx`` can't reach Amazon product pages or Goodreads search: the former
serves a captcha, the latter a CloudFront ``202`` with an empty body. Both
challenges are designed to be cleared by a *real* browser executing JavaScript,
so we drive one via Playwright. A short warm-up hit on the site's homepage lets
the WAF run its proof-of-work and set its token cookie before we navigate to the
page we actually want — without that warm-up the first real request is still
challenged (verified against Goodreads' ``aws-waf-token``).

Playwright is a heavy, optional dependency, imported lazily so the rest of the
CLI keeps working without it. It drives the system Google Chrome by default
(``channel="chrome"``, no 150 MB browser download); if that's missing it falls
back to a Playwright-managed Chromium, which requires ``playwright install
chromium``.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

# Default Chrome UA; matched to a real desktop Chrome so the fingerprint is
# consistent with the headers Playwright sends.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Mask the most obvious headless tells the WAF fingerprints on.
_STEALTH = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
window.chrome = { runtime: {} };
"""

_LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]


class BrowserUnavailable(RuntimeError):
    """Raised when no usable browser backend is available."""


class Page:
    """Thin wrapper exposing the one operation callers need: fetch rendered HTML."""

    def __init__(self, page) -> None:
        self._page = page

    def _goto(self, url: str, settle_ms: int, timeout_ms: int) -> None:
        self._page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        self._page.wait_for_timeout(settle_ms)

    def html(self, url: str, settle_ms: int = 2500, timeout_ms: int = 30000) -> str:
        """Navigate to ``url`` and return the rendered HTML once it settles."""
        self._goto(url, settle_ms, timeout_ms)
        return self._page.content()

    def element_attrs(
        self,
        url: str,
        selector: str,
        attrs: tuple[str, ...],
        settle_ms: int = 2500,
        timeout_ms: int = 30000,
    ) -> dict[str, str | None] | None:
        """Navigate to ``url`` and return ``attrs`` of the first ``selector`` match.

        Returns ``None`` if the element isn't present. Reading a specific DOM
        element (rather than scraping the whole page) keeps us to the product's
        own data and off neighbouring carousels.
        """
        self._goto(url, settle_ms, timeout_ms)
        el = self._page.query_selector(selector)
        if el is None:
            return None
        return {name: el.get_attribute(name) for name in attrs}

    def read_fields(
        self,
        url: str,
        queries: tuple[tuple[str, str, str | None], ...],
        settle_ms: int = 2500,
        timeout_ms: int = 30000,
    ) -> dict[str, str | None]:
        """Navigate to ``url`` once and read several fields from it.

        ``queries`` is a tuple of ``(key, css_selector, attr)``; ``attr=None``
        reads the element's text. Missing elements yield ``None``. One navigation
        serves every field, so e.g. the cover image and the product title come
        back together without a second page load.
        """
        self._goto(url, settle_ms, timeout_ms)
        out: dict[str, str | None] = {}
        for key, selector, attr in queries:
            el = self._page.query_selector(selector)
            if el is None:
                out[key] = None
            elif attr is None:
                out[key] = el.inner_text()
            else:
                out[key] = el.get_attribute(attr)
        return out


@contextmanager
def browser_session(
    warmup_url: str | None = None,
    warmup_ms: int = 4000,
    headless: bool = True,
) -> Iterator[Page]:
    """Yield a :class:`Page` backed by a stealthed, WAF-warmed Chrome session.

    ``warmup_url`` (typically the target site's homepage) is visited first so the
    WAF challenge resolves and its token cookie is set before real navigation.
    Raises :class:`BrowserUnavailable` if Playwright isn't installed or no Chrome
    /Chromium can be launched.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:  # pragma: no cover - exercised via integration run
        raise BrowserUnavailable(
            "Playwright is not installed. Install the browser extra "
            "(`uv pip install 'review[browser]'`) or run `uv run --with playwright …`."
        ) from e

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=headless, args=_LAUNCH_ARGS)
        except Exception:
            try:
                browser = p.chromium.launch(headless=headless, args=_LAUNCH_ARGS)
            except Exception as e:  # pragma: no cover - environment dependent
                raise BrowserUnavailable(
                    "Could not launch Chrome or Chromium. Install Google Chrome, "
                    "or run `playwright install chromium`."
                ) from e
        try:
            ctx = browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1280, "height": 900},
                locale="en-US",
            )
            ctx.add_init_script(_STEALTH)
            page = ctx.new_page()
            if warmup_url:
                page.goto(warmup_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(warmup_ms)
            yield Page(page)
        finally:
            browser.close()
