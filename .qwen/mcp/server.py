"""Stdio MCP for Qwen Code. Wraps .qwen/tools/desk.py. Never dumps article bodies."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from mcp.server import MCPServer
from mcp_types import ToolAnnotations

os.environ.setdefault("PYTHONUNBUFFERED", "1")
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from utf8io import configure as _utf8

    _utf8()
except Exception:
    pass
logging.basicConfig(stream=sys.stderr, level=logging.WARNING)

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / ".qwen" / "tools"
PYTHON = sys.executable
MAX_STDERR = 800
MAX_RAW = 4000

mcp = MCPServer("desk")


def _json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _last_json(text: str) -> dict:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    for line in reversed(lines):
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    snippet = (text or "").strip()[:MAX_RAW]
    return {"ok": False, "error": "no json line", "raw": snippet}


def _run(argv: list[str], timeout: int = 180) -> dict:
    proc = subprocess.run(
        [PYTHON, str(TOOLS / "desk.py"), "--root", str(ROOT), *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
        timeout=timeout,
        env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
    )
    out = _last_json(proc.stdout)
    if proc.returncode != 0:
        out["ok"] = False
    err = (proc.stderr or "").strip()
    if err and not out.get("ok", True):
        out["stderr"] = err[:MAX_STDERR]
    return out


def _date(date: str) -> list[str]:
    d = (date or "").strip()
    return ["--date", d] if d else []


@mcp.tool(
    description="Issue start: hot lists + four-line RSS + lab hits + quotes. Writes 线索.json. Returns ok, date, labs.missing, fetch_urls counts. No article bodies.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=False,
)
def plan(date: str = "") -> str:
    return _json(_run(["plan", *_date(date)], timeout=120))


@mcp.tool(
    description="One news line RSS/JSON within the 7-day window. line=人工智能|科技|娱乐|动漫. Returns n, fetch_urls (title/url/date only), labs.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=False,
)
def feed(line: str, date: str = "") -> str:
    if not (line or "").strip():
        return _json({"ok": False, "error": "missing line"})
    return _json(_run(["feed", "--line", line.strip(), *_date(date)], timeout=90))


@mcp.tool(
    description="Weibo/Baidu/IT之家/Douban/Bilibili hot lists. Writes 榜单.json. Returns n, headline_pool, counts.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=False,
)
def hot(date: str = "") -> str:
    return _json(_run(["hot", *_date(date)], timeout=60))


@mcp.tool(
    description="Tencent quotes. Writes 行情.md. Returns ok, rows (name/price/pct) or error.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=False,
)
def quotes(date: str = "") -> str:
    return _json(_run(["quotes", *_date(date)], timeout=30))


@mcp.tool(
    description="Ping feeds.json sources. Skip dead hosts. Returns n, feeds.",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True),
    structured_output=False,
)
def check_feeds() -> str:
    return _json(_run(["check"], timeout=60))


@mcp.tool(
    description="Try /rss /feed paths on a URL. Returns tries. Do not use on dead hosts.",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True),
    structured_output=False,
)
def probe(url: str) -> str:
    if not (url or "").startswith("http"):
        return _json({"ok": False, "error": "missing url"})
    return _json(_run(["probe", "--url", url.strip()], timeout=40))


@mcp.tool(
    description="List material files for a date (paths only, no bodies). For makeup slot picking.",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True),
    structured_output=False,
)
def materials(date: str) -> str:
    if not (date or "").strip():
        return _json({"ok": False, "error": "missing date"})
    return _json(_run(["materials", "--date", date.strip()], timeout=20))


@mcp.tool(
    description="Start llama.cpp or report /v1. probe=true: ping only, do not load GPU. Returns port, v1, skipped.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=False,
)
def serve(probe: bool = False) -> str:
    argv = ["serve"]
    if probe:
        argv.append("--probe")
    return _json(_run(argv, timeout=180))


@mcp.tool(
    description="Ping writer /v1 endpoints (llama.cpp first, then backup). Does not start GPU. Returns endpoints[].",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True),
    structured_output=False,
)
def writer_status() -> str:
    return _json(_run(["api"], timeout=20))


@mcp.tool(
    description="Write one article via local /v1. Returns path, chars, via. Never returns body. Editor after makeup slots.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False),
    structured_output=False,
)
def copy(date: str, id: str, title: str, line: str, source: str, kind: str = "普通", chars: int = 0) -> str:
    if not all([(date or "").strip(), (id or "").strip(), (title or "").strip(), (line or "").strip(), (source or "").strip()]):
        return _json({"ok": False, "error": "need date,id,title,line,source"})
    argv = [
        "copy",
        "--date",
        date.strip(),
        "--id",
        id.strip(),
        "--title",
        title.strip(),
        "--line",
        line.strip(),
        "--kind",
        (kind or "普通").strip(),
        "--source",
        source.strip(),
    ]
    if chars:
        argv.extend(["--chars", str(int(chars))])
    return _json(_run(argv, timeout=180))


@mcp.tool(
    description="Fill all slots in desk/版式/<date>.json (max 20). Returns n, items (path/chars/id). Never returns bodies. Fails without makeup json.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False),
    structured_output=False,
)
def copy_lineup(date: str) -> str:
    if not (date or "").strip():
        return _json({"ok": False, "error": "missing date"})
    return _json(_run(["copy", "--lineup", "--date", date.strip()], timeout=3600))


@mcp.tool(
    description="Scan desk/稿件/<date>/ into 目录.json. Returns n, items (hed/kind/chars/path), total_chars. No bodies.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=False,
)
def pack(date: str) -> str:
    if not (date or "").strip():
        return _json({"ok": False, "error": "missing date"})
    return _json(_run(["pack", "--date", date.strip()], timeout=20))


@mcp.tool(
    description="Compose YYYY-MM-DD.html from 版式 json + 稿件. Fails if pages missing (no auto layout). Returns html, pages, n_copy.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=False,
)
def compose(date: str) -> str:
    if not (date or "").strip():
        return _json({"ok": False, "error": "missing date"})
    return _json(_run(["compose", "--date", date.strip()], timeout=30))


@mcp.tool(
    description="Export each HTML page to PNG and measure px/ratio. layout-check only. Returns dir, measure[], expect_png_width_px, warnings. No VL.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=False,
)
def review(date: str, pages: str = "") -> str:
    if not (date or "").strip():
        return _json({"ok": False, "error": "missing date"})
    argv = ["review", "--date", date.strip()]
    if (pages or "").strip():
        argv.extend(["--pages", pages.strip()])
    return _json(_run(argv, timeout=300))


if __name__ == "__main__":
    mcp.run(transport="stdio")
