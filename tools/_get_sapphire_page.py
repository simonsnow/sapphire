#!/usr/bin/env python3
"""Headless render of a Sapphire web UI page — screenshot + post-JS DOM dump.

Invoked via tools/get-sapphire-page.sh. Auth follows ask-sapphire.sh:
login form CSRF + cookie jar over the self-signed local cert. Cookies are
then transplanted into a Playwright chromium context so the SPA can finish
rendering before capture.

Outputs:
  /tmp/sapphire-page-<route>.png  — viewport screenshot
  /tmp/sapphire-page-<route>.html — rendered DOM (post-JS)
"""
import asyncio
import os
import re
import sys
from pathlib import Path

import requests
import urllib3
from playwright.async_api import async_playwright

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE = "https://localhost:8073"
PASSWORD = os.environ.get("SAPPHIRE_PASSWORD", "changeme")

# Friendly names → hash fragments. Anything else is treated as a raw route
# (a leading '#' is added if missing). Settings sub-tabs aren't deep-linkable
# yet, so 'dashboard'/'apps' both land on #settings — use the tab strip from
# there if you need a specific tab.
ROUTE_ALIASES = {
    "chat": "#chat",
    "store": "#store",
    "settings": "#settings",
    "dashboard": "#settings",
    "apps": "#settings",
    "plugins": "#settings",
    "help": "#help",
    "mind": "#mind",
    "prompts": "#prompts",
    "toolsets": "#toolsets",
    "spices": "#spices",
    "schedule": "#schedule",
}


def _login() -> requests.Session:
    s = requests.Session()
    s.verify = False
    r = s.get(f"{BASE}/login", timeout=10)
    r.raise_for_status()
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', r.text)
    if not m:
        raise RuntimeError("could not extract login CSRF from /login")
    s.post(
        f"{BASE}/login",
        data={"password": PASSWORD, "csrf_token": m.group(1)},
        timeout=10,
        allow_redirects=False,
    )
    if not s.cookies:
        raise RuntimeError("login produced no cookies — check SAPPHIRE_PASSWORD")
    return s


async def _capture(route: str, width: int, height: int) -> tuple[Path, Path]:
    # Full URL passed (file://, http://, https://...) → no auth, no fragment
    # construction. Useful for local mockups (tmp/*.html via file://) and
    # external pages.
    is_full_url = "://" in route

    if is_full_url:
        url = route
        cookies = []
        # Derive a stable filename from the URL: last path segment + hash.
        m = re.search(r"([^/]+?)(\.[a-z]+)?(#[a-z0-9-]+)?$", route, re.IGNORECASE)
        safe_base = (m.group(1) if m else "page").lower()
        safe_hash = (m.group(3) or "").lstrip("#").lower()
        safe = re.sub(r"[^a-z0-9]+", "-", f"{safe_base}-{safe_hash}".strip("-")).strip("-") or "page"
    else:
        sess = _login()
        cookies = [{"name": c.name, "value": c.value, "url": BASE} for c in sess.cookies]
        fragment = ROUTE_ALIASES.get(route)
        if fragment is None:
            fragment = route if route.startswith("#") else f"#{route}"
        url = f"{BASE}/{fragment}"
        safe = re.sub(r"[^a-z0-9]+", "-", route.lower()).strip("-") or "page"
    out_png = Path(f"/tmp/sapphire-page-{safe}.png")
    out_html = Path(f"/tmp/sapphire-page-{safe}.html")

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(
            viewport={"width": width, "height": height},
            ignore_https_errors=True,
        )
        if cookies:
            await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        # Sapphire holds open SSE/long-poll streams, so 'networkidle' never
        # fires. Navigate on 'domcontentloaded' and let the SPA's hash router
        # settle — views are dynamic-imported and mounted into a pre-existing
        # #view-<id>.active div.
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(1500)
        await page.screenshot(path=str(out_png), full_page=False)
        out_html.write_text(await page.content(), encoding="utf-8")
        await browser.close()

    return out_png, out_html


def main() -> int:
    route = sys.argv[1] if len(sys.argv) > 1 else "chat"
    width = int(sys.argv[2]) if len(sys.argv) > 2 else 1440
    height = int(sys.argv[3]) if len(sys.argv) > 3 else 900

    try:
        png, html = asyncio.run(_capture(route, width, height))
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print(str(png))
    print(str(html))
    return 0


if __name__ == "__main__":
    sys.exit(main())
