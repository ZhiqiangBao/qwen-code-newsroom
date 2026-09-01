#!/usr/bin/env python3
"""Split newspaper HTML by page and screenshot each section with Edge. No VL."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PAGE_W = 912
WINDOW_H = 3600
SCALE = 2
PAPER = "#f4f1ea"
PAGE_CSS = re.compile(r"\.page\s*\{[^}]*?width:\s*min\(\s*(\d+)px", re.S)
PAPER_CSS = re.compile(r"--paper\s*:\s*(#[0-9a-fA-F]{3,8})")


def detect_page(html: str, fallback_w: int, fallback_paper: str) -> tuple[int, str]:
    """Read page width and paper colour from the newspaper's own CSS.

    Standards live in rules/ (R5) and are baked into the HTML by the editor; the
    exporter must not carry a second copy of them.
    """
    m = PAGE_CSS.search(html)
    width = int(m.group(1)) if m else fallback_w
    p = PAPER_CSS.search(html)
    return width, (p.group(1) if p else fallback_paper)


def find_edge() -> Path:
    env = os.environ
    candidates = [
        Path(env.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Microsoft/Edge/Application/msedge.exe",
        Path(env.get("ProgramFiles", r"C:\Program Files"))
        / "Microsoft/Edge/Application/msedge.exe",
        Path(env.get("LOCALAPPDATA", "")) / "Microsoft/Edge/Application/msedge.exe",
    ]
    for p in candidates:
        if p.is_file():
            return p
    raise SystemExit("msedge.exe not found")


def latest_html(root: Path) -> Path:
    files = sorted(root.glob("20[0-9][0-9]-[0-9][0-9]-[0-9][0-9].html"))
    if not files:
        raise SystemExit("no YYYY-MM-DD.html in project root")
    return files[-1]


def split_pages(html: str, html_path: Path, page_w: int, paper: str) -> list[tuple[str, str]]:
    marker = '<section class="page"'
    idxs: list[int] = []
    pos = 0
    while True:
        found = html.find(marker, pos)
        if found < 0:
            break
        idxs.append(found)
        pos = found + 1
    head_end = html.find("<body>")
    if head_end < 0:
        raise SystemExit("HTML missing <body>")
    head = re.sub(r'(?s)<nav class="nav">.*?</nav>', "", html[:head_end])
    src_uri = html_path.parent.resolve().as_uri()
    if not src_uri.endswith("/"):
        src_uri += "/"
    # Local stylesheets get inlined: the export runs from a temp directory, and a
    # relative <link> would not resolve there. The HTML on disk keeps the link, so
    # css/site.css stays the only place styles are edited.
    for tag in re.findall(r'<link[^>]+rel="stylesheet"[^>]*>', head):
        href = re.search(r'href="([^"]+)"', tag)
        if not href or href.group(1).startswith(("http", "//")):
            continue
        sheet = (html_path.parent / href.group(1)).resolve()
        if sheet.is_file():
            head = head.replace(tag, "<style>\n" + sheet.read_text(encoding="utf-8") + "\n</style>")
    extra = (
        f'<base href="{src_uri}">'
        "<style>body{background:#00ff00 !important;margin:0 !important}"
        f".page{{width:{page_w}px !important;margin:0 !important;box-shadow:none !important;"
        f"padding:14px 26px 22px !important;background:{paper} !important}}</style>"
    )
    head = head.replace("</head>", extra + "</head>")
    pages: list[tuple[str, str]] = []
    for i, start in enumerate(idxs):
        end = idxs[i + 1] if i + 1 < len(idxs) else html.find("</html>")
        sec = html[start:end]
        close = sec.find("</section>")
        if close < 0:
            continue
        sec = sec[: close + len("</section>")]
        m = re.search(r'id="([a-zA-Z0-9_-]+)"', sec)
        sid = m.group(1) if m else f"p{i + 1}"
        pages.append((sid, head + "<body>" + sec + "</body></html>"))
    return pages


def screenshot(edge: Path, src_html: Path, out_png: Path, page_w: int, scale: int) -> None:
    uri = src_html.resolve().as_uri()
    subprocess.run(
        [
            str(edge),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            "--disable-extensions",
            f"--force-device-scale-factor={scale}",
            "--virtual-time-budget=20000",
            f"--window-size={page_w},{WINDOW_H}",
            f"--screenshot={out_png}",
            uri,
        ],
        check=False,
        capture_output=True,
    )


def crop_sentinel(png_path: Path) -> str | None:
    """Crop green sentinel. Return a warning string if the page looks taller than the window."""
    from PIL import Image

    with Image.open(png_path) as src:
        im = src.convert("RGB")
    w, h = im.size
    px = im.load()
    bg = px[w // 2, h - 2]
    if bg[1] < 200 or bg[0] > 80 or bg[2] > 80:
        return f"{png_path.name} 底部不是哨兵绿，版面可能高于窗口"
    warn = None

    def row_ink(y: int) -> bool:
        for x in range(0, w, 16):
            r, g, b = px[x, y]
            if abs(r - bg[0]) > 12 or abs(g - bg[1]) > 12 or abs(b - bg[2]) > 12:
                return True
        return False

    hit = -1
    for y in range(h - 1, -1, -4):
        if row_ink(y):
            hit = y
            break
    if hit < 0:
        im.close()
        return warn
    bottom = hit
    for y in range(min(h - 1, hit + 4), hit, -1):
        if row_ink(y):
            bottom = y
            break
    cut = min(h, max(200, bottom + 1))
    cropped = im.crop((0, 0, w, cut))
    im.close()
    cropped.save(png_path)
    cropped.close()
    return warn


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        print(json.dumps({"ok": False, "error": "需要 pillow"}, ensure_ascii=False))
        return 1

    parser = argparse.ArgumentParser()
    parser.add_argument("--html", default="")
    parser.add_argument("--pages", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--width", type=int, default=0, help="页宽 px；默认从 HTML 的 .page CSS 读取")
    parser.add_argument("--scale", type=int, default=0, help="导出倍率；默认取脚本内 SCALE")
    args = parser.parse_args()

    root = Path.cwd()
    html_path = Path(args.html).resolve() if args.html else latest_html(root)
    if not html_path.is_file():
        print(json.dumps({"ok": False, "error": f"missing html: {html_path}"}, ensure_ascii=False))
        return 1

    want = {p.strip().lower() for p in args.pages.split(",") if p.strip()}
    if not args.output:
        print(
            json.dumps(
                {"ok": False, "error": "必须给 --output；导出目录模板见 rules/disk.md「版面」行"},
                ensure_ascii=False,
            )
        )
        return 1
    out_dir = Path(args.output).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_html = html_path.read_text(encoding="utf-8")
    # The stylesheet may be a separate file (css/site.css); page geometry lives there.
    probe = raw_html + "".join(
        (html_path.parent / m).resolve().read_text(encoding="utf-8")
        for m in re.findall(r'<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"', raw_html)
        if not m.startswith(("http", "//")) and (html_path.parent / m).is_file()
    )
    page_w, paper = detect_page(probe, PAGE_W, PAPER)
    if args.width:
        page_w = args.width
    scale = args.scale or SCALE
    pages = split_pages(raw_html, html_path, page_w, paper)
    if want:
        pages = [(sid, doc) for sid, doc in pages if sid.lower() in want]
    if not pages:
        print(json.dumps({"ok": False, "error": "no matching pages"}, ensure_ascii=False))
        return 1

    edge = find_edge()
    exported: list[str] = []
    measure: list[dict] = []
    warnings: list[str] = []
    with tempfile.TemporaryDirectory(prefix="layout-export-") as tmp:
        tmp_path = Path(tmp)
        for i, (sid, doc) in enumerate(pages, 1):
            src = tmp_path / f"{sid}.html"
            raw = tmp_path / f"{sid}.raw.png"
            src.write_text(doc, encoding="utf-8")
            screenshot(edge, src, raw, page_w, scale)
            dest = out_dir / f"{i:02d}_{sid.upper()}.png"
            if not raw.is_file():
                print(json.dumps({"ok": False, "error": f"screenshot failed: {sid}"}, ensure_ascii=False))
                return 1
            note = crop_sentinel(raw)
            if note:
                warnings.append(f"{sid}: {note}")
            dest.write_bytes(raw.read_bytes())
            exported.append(dest.name)
            with Image.open(dest) as png:
                w_px, h_px = png.size
            measure.append(
                {
                    "page": dest.name,
                    "px": [w_px, h_px],
                    "ratio": round(h_px / w_px, 2) if w_px else None,
                }
            )

    payload = {
        "ok": True,
        "dir": str(out_dir),
        "n": len(exported),
        "pages": exported,
        "page_width_px": page_w,
        "scale": scale,
        "expect_png_width_px": page_w * scale,
        "window_h_px": WINDOW_H,
        "measure": measure,
    }
    if warnings:
        payload["warnings"] = warnings
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
