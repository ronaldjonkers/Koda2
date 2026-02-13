"""Browser control service using Playwright for Chrome CDP automation."""

from __future__ import annotations

import asyncio
import base64
from typing import Any, Optional

from koda2.logging_config import get_logger

logger = get_logger(__name__)

# Lazy import — playwright is optional
_playwright = None
_browser = None


class BrowserService:
    """Control a headless Chrome browser for web automation."""

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    async def _ensure_browser(self) -> None:
        """Launch browser if not already running."""
        if self._page and not self._page.is_closed():
            return

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError(
                "playwright is not installed. Run: pip install playwright && playwright install chromium"
            )

        if not self._playwright:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-gpu"],
            )
            logger.info("browser_launched")

        if not self._context:
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )

        self._page = await self._context.new_page()

    async def browse_url(self, url: str, wait_for: str = "load") -> dict[str, Any]:
        """Navigate to a URL and return page content.

        Args:
            url: The URL to navigate to.
            wait_for: Wait condition — "load", "domcontentloaded", or "networkidle".

        Returns:
            Dict with title, url, text content, and screenshot (base64).
        """
        await self._ensure_browser()

        try:
            await self._page.goto(url, wait_until=wait_for, timeout=30000)
        except Exception as exc:
            return {"error": f"Navigation failed: {exc}", "url": url}

        title = await self._page.title()
        # Extract readable text content
        text = await self._page.evaluate("""
            () => {
                const sel = document.querySelectorAll('article, main, [role="main"], .content, #content, body');
                const el = sel[0] || document.body;
                return el.innerText.substring(0, 8000);
            }
        """)

        # Take screenshot
        screenshot_bytes = await self._page.screenshot(type="png", full_page=False)
        screenshot_b64 = base64.b64encode(screenshot_bytes).decode()

        logger.info("browser_navigated", url=url, title=title)
        return {
            "title": title,
            "url": self._page.url,
            "text": text[:5000],
            "screenshot_b64": screenshot_b64[:100] + "...(truncated)",
            "screenshot_size": len(screenshot_bytes),
        }

    async def browser_action(
        self,
        action: str,
        selector: str = "",
        text: str = "",
        url: str = "",
    ) -> dict[str, Any]:
        """Perform a browser action.

        Args:
            action: One of "click", "type", "scroll", "screenshot", "evaluate", "goto", "back", "forward".
            selector: CSS selector for click/type actions.
            text: Text to type, or JS code for evaluate.
            url: URL for goto action.
        """
        await self._ensure_browser()

        try:
            if action == "goto" and url:
                await self._page.goto(url, wait_until="load", timeout=30000)
                return {"action": "goto", "url": self._page.url, "title": await self._page.title()}

            elif action == "click" and selector:
                await self._page.click(selector, timeout=5000)
                await self._page.wait_for_load_state("load", timeout=5000)
                return {"action": "click", "selector": selector, "url": self._page.url}

            elif action == "type" and selector and text:
                await self._page.fill(selector, text)
                return {"action": "type", "selector": selector, "text_length": len(text)}

            elif action == "scroll":
                direction = text or "down"
                delta = 500 if direction == "down" else -500
                await self._page.mouse.wheel(0, delta)
                return {"action": "scroll", "direction": direction}

            elif action == "screenshot":
                screenshot_bytes = await self._page.screenshot(type="png", full_page=False)
                path = f"data/screenshots/browser_{asyncio.get_event_loop().time():.0f}.png"
                from pathlib import Path
                Path("data/screenshots").mkdir(parents=True, exist_ok=True)
                Path(path).write_bytes(screenshot_bytes)
                return {"action": "screenshot", "path": path, "size": len(screenshot_bytes)}

            elif action == "evaluate" and text:
                result = await self._page.evaluate(text)
                return {"action": "evaluate", "result": str(result)[:3000]}

            elif action == "back":
                await self._page.go_back()
                return {"action": "back", "url": self._page.url}

            elif action == "forward":
                await self._page.go_forward()
                return {"action": "forward", "url": self._page.url}

            elif action == "get_text":
                text_content = await self._page.evaluate("() => document.body.innerText.substring(0, 8000)")
                return {"action": "get_text", "text": text_content[:5000]}

            else:
                return {"error": f"Unknown action: {action}"}

        except Exception as exc:
            return {"error": str(exc), "action": action}

    async def close(self) -> None:
        """Close the browser."""
        try:
            if self._page and not self._page.is_closed():
                await self._page.close()
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        finally:
            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None
            logger.info("browser_closed")
