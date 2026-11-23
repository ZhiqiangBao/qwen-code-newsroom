"""Stdio MCP for Qwen Code. Wraps .qwen/tools/desk.py. Never dumps article bodies."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
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


@contextmanager
def _body_tmp(body: str, prefix: str = "desk-body-"):
    fd, tmp = tempfile.mkstemp(prefix=prefix, suffix=".txt")
    try:
        os.write(fd, body.encode("utf-8"))
        os.close(fd)
        yield tmp
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


@mcp.tool(
    description="Issue start: hot lists + four-line RSS + lab hits + quotes. Writes 线索.json. Returns ok, date, labs.missing, fetch_urls counts. No article bodies.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=False,
)
def plan(date: str = "") -> str:
    return _json(_run(["plan", *_date(date)], timeout=120))


@mcp.tool(
    description="After plan: this line's article URLs plus this issue's hot titles (Weibo/Baidu words, no search-page URLs). Returns fetch_urls, hot, labs_missing. line=人工智能|科技|娱乐|动漫.",
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
    description="Quotes: Tencent A-shares + Baidu FinScope index overview JSON. Writes 行情.md. Returns ok, rows (name/price/pct). Not the finance.baidu.com HTML shell.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=False,
)
def quotes(date: str = "") -> str:
    return _json(_run(["quotes", *_date(date)], timeout=30))


@mcp.tool(
    description="Save one material. Auto-names 深挖-01/普通-01/快讯.md/补-1. Returns path,id,source. Never returns body. kind=深挖|普通|快讯|补. line=数据|人工智能|科技|娱乐|动漫.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False),
    structured_output=False,
)
def ingest(
    date: str,
    line: str,
    kind: str,
    title: str,
    body: str,
    url: str = "",
    day: str = "",
    note: str = "",
    pic: str = "",
) -> str:
    if not all([(line or "").strip(), (kind or "").strip(), (title or "").strip(), (body or "").strip()]):
        return _json({"ok": False, "error": "need line,kind,title,body"})
    with _body_tmp(body, "desk-ingest-") as tmp:
        argv = [
            "ingest",
            "--line",
            line.strip(),
            "--kind",
            kind.strip(),
            "--title",
            title.strip(),
            "--body-file",
            tmp,
            *_date(date),
        ]
        if (url or "").strip():
            argv.extend(["--url", url.strip()])
        if (day or "").strip():
            argv.extend(["--day", day.strip()])
        if (note or "").strip():
            argv.extend(["--note", note.strip()])
        if (pic or "").strip():
            argv.extend(["--pic", pic.strip()])
        return _json(_run(argv, timeout=30))


@mcp.tool(
    description="Save 版式 JSON, 校对 md, or 版面 report. 版式: auto-fills id/line/kind, hangs 快讯 to shorts, returns page_chars. Rejects bodies. kind=版式|校对|版面.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=False,
)
def put(date: str, kind: str, body: str) -> str:
    if not (kind or "").strip() or not (body or "").strip():
        return _json({"ok": False, "error": "need kind,body"})
    with _body_tmp(body, "desk-put-") as tmp:
        return _json(
            _run(["put", "--kind", kind.strip(), "--body-file", tmp, *_date(date)], timeout=30)
        )


@mcp.tool(
    description="Editor: verify files landed. kind=线索|素材|版式|稿件|校对|版面|图|全部. Optional line (materials) or path (one file). Returns ok, chars, empty, missing. Never returns bodies. Do not read_file desk/.",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True),
    structured_output=False,
)
def landed(date: str, kind: str = "全部", line: str = "", path: str = "") -> str:
    if (path or "").strip():
        argv = ["landed", "--path", path.strip(), *_date(date)]
        return _json(_run(argv, timeout=20))
    argv = ["landed", "--kind", (kind or "全部").strip() or "全部", *_date(date)]
    if (line or "").strip():
        argv.extend(["--line", line.strip()])
    return _json(_run(argv, timeout=20))


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
    description="List materials for makeup: path, id, kind, line, title, chars, suggest, n_flash, pic. Never returns bodies.",
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
    description="Write one article via local /v1. Returns path, chars, via. Never returns body. Prefer copy_lineup from_materials after ingest.",
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
    description="Write only stories selected in this issue's validated evidence table. Optional ids reruns selected drafts. Returns manuscript paths and lengths.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False),
    structured_output=False,
)
def copy_lineup(date: str, ids: str = "", force: bool = False, from_materials: bool = False) -> str:
    if not (date or "").strip():
        return _json({"ok": False, "error": "missing date"})
    argv = ["copy", "--date", date.strip()]
    if from_materials:
        argv.append("--materials")
    else:
        argv.append("--lineup")
    if (ids or "").strip():
        argv.extend(["--ids", ids.strip()])
    if force:
        argv.append("--force")
    return _json(_run(argv, timeout=3600))


@mcp.tool(
    description="Turn 稿件 MD into desk/稿件/<date>/目录.json. Makeup fills slots from this. Returns n, items (id/hed/kind/role/chars/n_para/source/pic), total_chars. Never bodies.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=False,
)
def pack(date: str) -> str:
    if not (date or "").strip():
        return _json({"ok": False, "error": "missing date"})
    return _json(_run(["pack", "--date", date.strip()], timeout=20))


@mcp.tool(
    description="Compose YYYY-MM-DD.html from the page plan and selected drafts. Includes public sources and article-bound figures. Returns the local HTML path.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=False,
)
def compose(date: str) -> str:
    if not (date or "").strip():
        return _json({"ok": False, "error": "missing date"})
    return _json(_run(["compose", "--date", date.strip()], timeout=30))


@mcp.tool(
    description="Review the prepared candidate, export issue PNGs and report layout blockers. Omit pages to record one complete candidate check.",
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


@mcp.tool(
    description="Save the editor's dated JSON evidence table with chosen stories, source references, and analysis question. Does not write articles.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=False,
)
def select(date: str, evidence: str) -> str:
    with _body_tmp(evidence, prefix="desk-evidence-") as body_file:
        return _json(_run(["select", "--date", date, "--body-file", body_file], timeout=20))


@mcp.tool(
    description="Prepare the exact web candidate and its fingerprint for review. Leaves the published homepage intact.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=False,
)
def prepare(date: str) -> str:
    return _json(_run(["prepare", "--date", date], timeout=60))


@mcp.tool(
    description="List files in img/<date>/ (name, kb only). No pixels. For filling 版式 figures src.",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True),
    structured_output=False,
)
def images(date: str) -> str:
    if not (date or "").strip():
        return _json({"ok": False, "error": "missing date"})
    return _json(_run(["images", "--date", date.strip()], timeout=10))


@mcp.tool(
    description="Copy one image file into img/<date>/<name>. Returns path, kb. Use after image_gen. Does not generate.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=False,
)
def place(date: str, src: str, name: str = "") -> str:
    if not (date or "").strip() or not (src or "").strip():
        return _json({"ok": False, "error": "need date,src"})
    argv = ["place", "--date", date.strip(), "--src", src.strip()]
    if (name or "").strip():
        argv.extend(["--name", name.strip()])
    return _json(_run(argv, timeout=20))


@mcp.tool(
    description="Editor: set figures[].src on 版式 json after place. id=figure id, src=img/<date>/file. Does not rewrite copy. Returns id, src.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=False,
)
def figure(date: str, id: str, src: str) -> str:
    if not all([(date or "").strip(), (id or "").strip(), (src or "").strip()]):
        return _json({"ok": False, "error": "need date,id,src"})
    return _json(
        _run(["figure", "--date", date.strip(), "--id", id.strip(), "--src", src.strip()], timeout=10)
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
