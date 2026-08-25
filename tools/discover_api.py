"""Discovery phase: intercept the target site's network traffic.

This script is NOT used by the daily run. It exists to (re)discover the
application's JSON endpoints when the site changes, and to produce the raw
material for `docs/api.md`.

It drives a real browser: the anti-bot JavaScript challenge is passed by the
browser itself, exactly as for a human visitor. No protection is circumvented
or reimplemented.

    uv run --extra discovery python tools/discover_api.py --out var/discovery
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import Page, Response, sync_playwright

BASE = "https://encheres-domaine.gouv.fr"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
JSON_HINT = re.compile(r"json", re.IGNORECASE)
SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")


@dataclass(slots=True)
class Capture:
    """One HTTP response observed while browsing."""

    url: str
    method: str
    status: int
    content_type: str
    body_path: str | None = None
    keys: list[str] = field(default_factory=list)
    error: str | None = None


def slugify(url: str, index: int) -> str:
    parsed = urlparse(url)
    stem = SAFE_NAME.sub("_", f"{parsed.path}_{parsed.query}").strip("_")[:110]
    return f"{index:03d}_{stem or 'root'}.json"


def top_level_shape(payload: Any) -> list[str]:
    """Summarise the shape of a response without dumping its contents."""
    if isinstance(payload, dict):
        return sorted(str(k) for k in payload)
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return ["[]", *sorted(f"[].{k}" for k in payload[0])]
    if isinstance(payload, list):
        return [f"[] len={len(payload)}"]
    return [type(payload).__name__]


class Recorder:
    """Accumulate JSON responses and write their bodies to disk."""

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.bodies = out_dir / "bodies"
        self.bodies.mkdir(parents=True, exist_ok=True)
        self.captures: list[Capture] = []

    def on_response(self, response: Response) -> None:
        content_type = response.headers.get("content-type", "")
        if not JSON_HINT.search(content_type):
            return
        capture = Capture(
            url=response.url,
            method=response.request.method,
            status=response.status,
            content_type=content_type,
        )
        try:
            payload = response.json()
        except Exception as exc:  # every anomaly is worth recording, not triaging
            capture.error = f"{type(exc).__name__}: {exc}"
        else:
            name = slugify(response.url, len(self.captures))
            path = self.bodies / name
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            capture.body_path = str(path.relative_to(self.out_dir))
            capture.keys = top_level_shape(payload)
        self.captures.append(capture)


def save_text(out_dir: Path, name: str, content: str) -> None:
    (out_dir / name).write_text(content, encoding="utf-8")


def _links(page: Page) -> list[str]:
    """Links of the current page, deduplicated."""
    raw = page.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))")
    return sorted({h for h in raw if isinstance(h, str)})


def _compliance(page: Page, out_dir: Path) -> None:
    """Record robots.txt and the terms of use before any other navigation."""
    for name, path in (("robots.txt", "/robots.txt"), ("cgu.html", "/cgu")):
        try:
            page.goto(f"{BASE}{path}", wait_until="networkidle", timeout=45_000)
            save_text(out_dir, name, page.content())
        except Exception as exc:  # discovery must never stop dead
            save_text(out_dir, name, f"ERREUR: {type(exc).__name__}: {exc}")


def _explore(page: Page, out_dir: Path, sale_id: str) -> None:
    """Vehicle category, sales list, then one sale, then one lot."""
    # The category page is the only one showing how the application filters
    # lots by category — a filter the daily run cannot yet apply API-side
    # (see docs/api.md §6).
    page.goto(f"{BASE}/categorie/vehicules", wait_until="networkidle", timeout=60_000)
    page.wait_for_timeout(4_000)
    save_text(out_dir, "categorie_vehicules.html", page.content())

    page.goto(f"{BASE}/ventes", wait_until="networkidle", timeout=60_000)
    page.wait_for_timeout(4_000)
    save_text(out_dir, "ventes.html", page.content())
    links = _links(page)
    save_text(out_dir, "ventes_links.json", json.dumps(links, indent=2))

    sale_href = (
        f"/vente/{sale_id}" if sale_id else next((h for h in links if h.startswith("/vente/")), "")
    )
    if not sale_href:
        return
    page.goto(f"{BASE}{sale_href}", wait_until="networkidle", timeout=60_000)
    page.wait_for_timeout(4_000)
    save_text(out_dir, "vente.html", page.content())
    lot_links = _links(page)
    save_text(out_dir, "vente_links.json", json.dumps(lot_links, indent=2))

    lot_href = next((h for h in lot_links if h.startswith("/lot/") or "/hermes/" in h), "")
    if lot_href:
        page.goto(f"{BASE}{lot_href}", wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(4_000)
        save_text(out_dir, "lot.html", page.content())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("var/discovery"))
    parser.add_argument("--headed", action="store_true", help="afficher le navigateur")
    parser.add_argument(
        "--sale-id", default="", help="id de vente à ouvrir (sinon : premier lien trouvé)"
    )
    args = parser.parse_args()

    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    recorder = Recorder(out_dir)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        context = browser.new_context(user_agent=UA, locale="fr-FR")
        page = context.new_page()
        page.on("response", recorder.on_response)

        _compliance(page, out_dir)
        _explore(page, out_dir, args.sale_id)

        cookies = context.cookies()
        save_text(out_dir, "cookies.json", json.dumps(cookies, indent=2))
        browser.close()

    report = [
        {
            "url": c.url,
            "method": c.method,
            "status": c.status,
            "content_type": c.content_type,
            "body": c.body_path,
            "shape": c.keys,
            "error": c.error,
        }
        for c in recorder.captures
    ]
    save_text(out_dir, "captures.json", json.dumps(report, ensure_ascii=False, indent=2))
    print(f"{len(report)} réponses JSON capturées -> {out_dir}")
    for capture in recorder.captures:
        print(f"  {capture.status} {capture.method} {capture.url[:130]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
