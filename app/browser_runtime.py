"""Cloudflare Browser Run session manager for NEXUS milestone 1.

The browser itself runs on Cloudflare. This Python service is the control plane
and connects to the remote Chromium instance over the Chrome DevTools Protocol.
"""
from __future__ import annotations

import asyncio
import base64
import ipaddress
import os
import socket
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright


class BrowserConfigurationError(RuntimeError):
    pass


class UnsafeBrowserTarget(ValueError):
    pass


@dataclass
class RemoteBrowserSession:
    id: str
    cloudflare_id: str
    websocket_url: str
    live_view_url: str | None
    playwright: Playwright
    browser: Browser
    context: BrowserContext
    page: Page
    browser_use_session: Any | None = None


def _is_public_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def validate_public_url(url: str) -> str:
    """Allow only public HTTP(S) URLs; reject private, local and reserved targets."""
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise UnsafeBrowserTarget("Only public http:// and https:// URLs are allowed")
        if parsed.username or parsed.password:
            raise UnsafeBrowserTarget("URLs containing embedded credentials are not allowed")
        host = parsed.hostname.rstrip(".").lower()
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
            raise UnsafeBrowserTarget("Localhost targets are blocked")
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None:
            if not _is_public_ip(str(literal)):
                raise UnsafeBrowserTarget("Private or reserved IP targets are blocked")
        else:
            records = await asyncio.to_thread(
                socket.getaddrinfo, host, parsed.port or (443 if parsed.scheme == "https" else 80),
                0, socket.SOCK_STREAM,
            )
            addresses = {record[4][0] for record in records}
            if not addresses or any(not _is_public_ip(address) for address in addresses):
                raise UnsafeBrowserTarget("The hostname resolves to a private or reserved IP")
        return url
    except UnsafeBrowserTarget:
        raise
    except (ValueError, OSError) as exc:
        raise UnsafeBrowserTarget("The URL is invalid or its hostname cannot be resolved") from exc


class CloudflareBrowserManager:
    def __init__(self) -> None:
        self.account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
        self.api_token = os.getenv("CLOUDFLARE_BROWSER_RUN_TOKEN", "").strip()
        self.keep_alive_ms = min(max(int(os.getenv("CLOUDFLARE_BROWSER_KEEP_ALIVE_MS", "600000")), 10000), 1200000)
        self.sessions: dict[str, RemoteBrowserSession] = {}
        self._lock = asyncio.Lock()

    def configured(self) -> bool:
        return bool(self.account_id and self.api_token)

    def _require_config(self) -> None:
        if not self.configured():
            raise BrowserConfigurationError(
                "Configure CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_BROWSER_RUN_TOKEN "
                "(token permission: Browser Rendering - Edit)."
            )

    def _base(self) -> str:
        return f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/browser-run"

    async def create(self, initial_url: str = "https://example.com") -> dict[str, Any]:
        self._require_config()
        await validate_public_url(initial_url)
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self._base()}/devtools/browser",
                params={"keep_alive": self.keep_alive_ms, "targets": "true"},
                headers={"Authorization": f"Bearer {self.api_token}"},
            )
            response.raise_for_status()
            payload = response.json()
        if not payload.get("success", True):
            raise BrowserConfigurationError("Cloudflare could not create a browser session")
        result = payload.get("result") or payload
        cloudflare_id = result.get("sessionId") or result.get("session_id")
        if not cloudflare_id:
            raise BrowserConfigurationError("Cloudflare response did not include a browser session ID")
        targets = result.get("targets") or []
        live_view_url = next(
            (target.get("devtoolsFrontendUrl") for target in targets if target.get("devtoolsFrontendUrl")),
            None,
        )
        websocket_url = (
            f"wss://api.cloudflare.com/client/v4/accounts/{self.account_id}"
            f"/browser-run/devtools/browser/{cloudflare_id}"
        )
        playwright = await async_playwright().start()
        browser: Browser | None = None
        try:
            browser = await playwright.chromium.connect_over_cdp(
                websocket_url,
                headers={"Authorization": f"Bearer {self.api_token}"},
                timeout=30000,
            )
            # Reuse Browser Run's default context so Playwright and Browser Use
            # operate inside the same request-guarded browser context.
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            context.set_default_timeout(15000)
            context.set_default_navigation_timeout(30000)

            async def guard_request(route: Any) -> None:
                request_url = route.request.url
                if request_url.startswith(("about:", "data:", "blob:")):
                    await route.continue_()
                    return
                try:
                    await validate_public_url(request_url)
                    await route.continue_()
                except UnsafeBrowserTarget:
                    await route.abort("blockedbyclient")

            await context.route("**/*", guard_request)
            page = context.pages[0] if context.pages else await context.new_page()
            session = RemoteBrowserSession(
                id=str(uuid.uuid4()),
                cloudflare_id=cloudflare_id,
                websocket_url=websocket_url,
                live_view_url=live_view_url,
                playwright=playwright,
                browser=browser,
                context=context,
                page=page,
            )
            async with self._lock:
                self.sessions[session.id] = session
            await page.goto(initial_url, wait_until="domcontentloaded")
            return await self.describe(session)
        except Exception:
            if browser is not None:
                await browser.close()
            await playwright.stop()
            raise

    def get(self, session_id: str) -> RemoteBrowserSession:
        session = self.sessions.get(session_id)
        if not session:
            raise KeyError("Browser session not found or expired")
        return session

    async def describe(self, session: RemoteBrowserSession) -> dict[str, Any]:
        title = await session.page.title()
        return {
            "session_id": session.id,
            "cloudflare_session_id": session.cloudflare_id,
            "url": session.page.url,
            "title": title,
            "live_view_url": session.live_view_url,
            "status": "connected",
        }

    async def inspect(self, session: RemoteBrowserSession) -> dict[str, Any]:
        data = await self.describe(session)
        data["text"] = (await session.page.locator("body").inner_text(timeout=10000))[:12000]
        data["links"] = await session.page.locator("a[href]").evaluate_all(
            "(els) => els.slice(0, 40).map(a => ({text:(a.innerText||a.getAttribute('aria-label')||'').trim().slice(0,160), href:a.href}))"
        )
        image = await session.page.screenshot(type="jpeg", quality=65, full_page=False)
        data["screenshot_base64"] = base64.b64encode(image).decode("ascii")
        return data

    async def navigate(self, session: RemoteBrowserSession, url: str) -> dict[str, Any]:
        await validate_public_url(url)
        await session.page.goto(url, wait_until="domcontentloaded")
        return await self.inspect(session)

    async def close(self, session_id: str) -> None:
        async with self._lock:
            session = self.sessions.pop(session_id, None)
        if session:
            if session.browser_use_session is not None:
                try:
                    await session.browser_use_session.kill()
                except Exception:
                    pass
            try:
                await session.browser.close()
            finally:
                await session.playwright.stop()


browser_manager = CloudflareBrowserManager()
