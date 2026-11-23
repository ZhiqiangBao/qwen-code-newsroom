#!/usr/bin/env python3
"""Split newspaper HTML by page and screenshot each section with Edge. No VL."""
from __future__ import annotations

import argparse
import hashlib
import html as html_lib
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
MIN_RATIO = 1.35
MAX_RATIO = 1.75
PAGE_CSS = re.compile(r"\.page\s*\{[^}]*?width:\s*min\(\s*(\d+)px", re.S)
PAPER_CSS = re.compile(r"--paper\s*:\s*(#[0-9a-fA-F]{3,8})")


def detect_page(html: str, fallback_w: int, fallback_paper: str) -> tuple[int, str]:
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
    raise FileNotFoundError("msedge.exe not found")


def latest_html(root: Path) -> Path:
    files = sorted(root.glob("20[0-9][0-9]-[0-9][0-9]-[0-9][0-9].html"))
    if not files:
        raise FileNotFoundError("no YYYY-MM-DD.html in project root")
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
        raise ValueError("HTML missing <body>")
    head = re.sub(r'(?s)<nav class="nav">.*?</nav>', "", html[:head_end])
    src_uri = html_path.parent.resolve().as_uri()
    if not src_uri.endswith("/"):
        src_uri += "/"
    head = head.replace("<head>", f'<head><base href="{src_uri}">', 1)
    extra = ("<style>body{background:#00ff00 !important;margin:0 !important}"
             f".page{{width:{page_w}px !important;margin:0 !important;box-shadow:none !important;"
             f"background:{paper} !important}}</style>")
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
    result = subprocess.run(
        [
            str(edge),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            "--disable-extensions",
            "--allow-file-access-from-files",
            f"--user-data-dir={src_html.parent / 'edge-profile'}",
            f"--force-device-scale-factor={scale}",
            "--virtual-time-budget=20000",
            f"--window-size={page_w},{WINDOW_H}",
            f"--screenshot={out_png}",
            uri,
        ],
        check=False,
        capture_output=True,
        timeout=50,
    )
    if result.returncode != 0:
        raise RuntimeError(f"screenshot failed: {result.stderr.decode(errors='replace')[-500:]}")


def inspect_page(edge: Path, src_html: Path, page_w: int, scale: int, inner: bool) -> list[str]:
    # 与截图使用相同视口和浏览器配置；单独渲染的动态内容仍需人工核对。
    script = r"""<script>
addEventListener('load', () => {
  const errors = [];
  const page = document.querySelector('.page');
  if (!page) errors.push('未找到版面');
  else {
    if (INNER) {
      const folio = page.querySelector('.folio');
      const first = Array.from(page.children).find(e => {
        const r = e.getBoundingClientRect();
        return r.width && r.height && getComputedStyle(e).visibility !== 'hidden';
      });
      if (!folio || !first || (first !== folio && !first.contains(folio)))
        errors.push('[版头] 内页正文前缺少版头');
      else {
        const f = folio.getBoundingClientRect();
        for (const e of page.children) {
          if (e === first) continue;
          const r = e.getBoundingClientRect();
          if (r.width && r.height && r.top < f.bottom - 1) {
            errors.push('[版头] 内容出现在版头之前或与版头重叠'); break;
          }
        }
      }
    }
    for (const img of page.querySelectorAll('img')) {
      const r = img.getBoundingClientRect();
      const label = img.getAttribute('alt') || img.getAttribute('src') || '图片';
      if (!img.complete || !img.naturalWidth || !img.naturalHeight) {
        errors.push('[断图] ' + label); continue;
      }
      const style = getComputedStyle(img);
      if (!r.width || !r.height || style.visibility !== 'visible') {
        errors.push('[图片不可见] ' + label); continue;
      }
      const cw = img.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
      const ch = img.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
      const imageRatio = img.naturalWidth / img.naturalHeight;
      if (cw > 0 && ch > 0 && style.objectFit === 'cover' &&
          Math.abs(cw / ch / imageRatio - 1) > 0.02)
        errors.push('[裁图] ' + label);
      for (let parent = img.parentElement; parent && parent !== page; parent = parent.parentElement) {
        const ps = getComputedStyle(parent), pr = parent.getBoundingClientRect();
        const clipX = ['hidden','clip','scroll','auto'].includes(ps.overflowX);
        const clipY = ['hidden','clip','scroll','auto'].includes(ps.overflowY);
        if ((clipX && (r.left < pr.left - 1 || r.right > pr.right + 1)) ||
            (clipY && (r.top < pr.top - 1 || r.bottom > pr.bottom + 1))) {
          errors.push('[裁图] ' + label); break;
        }
      }
    }
  }
  document.body.setAttribute('data-review-errors', JSON.stringify(errors));
});
</script>""".replace('INNER', 'true' if inner else 'false')
    source = src_html.read_text(encoding="utf-8").replace('</body>', script + '</body>')
    src_html.write_text(source, encoding="utf-8")
    result = subprocess.run(
        [str(edge), '--headless=new', '--disable-gpu', '--hide-scrollbars',
         '--no-first-run', '--disable-extensions', '--allow-file-access-from-files',
         f'--user-data-dir={src_html.parent / "edge-profile"}',
         f'--force-device-scale-factor={scale}', '--virtual-time-budget=20000',
         f'--window-size={page_w},{WINDOW_H}', '--dump-dom', src_html.resolve().as_uri()],
        check=False, capture_output=True, timeout=50,
    )
    if result.returncode:
        raise RuntimeError('版面检查失败：' + result.stderr.decode(errors='replace')[-500:])
    dom = result.stdout.decode('utf-8', errors='replace')
    match = re.search(r'data-review-errors="([^"]*)"', dom)
    if not match:
        raise RuntimeError('版面检查未完成')
    return json.loads(html_lib.unescape(match.group(1)))


def crop_sentinel(png_path: Path) -> str | None:
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
        return f"{png_path.name} 未检测到版面"
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


def dimension_error(width: int, height: int, scale: int) -> str:
    if abs(width - PAGE_W * scale) > 10 or height <= 0:
        return f"[纸宽] 导出 {width}×{height} 像素，期望纸宽 {PAGE_W * scale}"
    ratio = height / width
    if ratio < MIN_RATIO:
        return f"[版面过短] 高宽比 {ratio:.4f} 低于 {MIN_RATIO}"
    if ratio > MAX_RATIO:
        return f"[长卷] 高宽比 {ratio:.4f} 超过 {MAX_RATIO}"
    return ""


def run(html: str | Path, output: str | Path, pages: str = "", width: int = 0, scale: int = 0) -> dict:
    try:
        from PIL import Image
    except ImportError:
        return {"ok": False, "error": "需要 pillow"}
    html_path = Path(html).resolve()
    if not html_path.is_file():
        return {"ok": False, "error": f"missing html: {html_path}"}
    if not output:
        return {"ok": False, "error": "必须给 output；见 rules/disk.md「版面」行"}
    out_dir = Path(output).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_html = html_path.read_text(encoding="utf-8")
    probe = raw_html + "".join(
        (html_path.parent / m).resolve().read_text(encoding="utf-8")
        for m in re.findall(r'<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"', raw_html)
        if not m.startswith(("http", "//")) and (html_path.parent / m).is_file()
    )
    page_w, paper = detect_page(probe, PAGE_W, PAPER)
    if width:
        page_w = width
    scale = scale or SCALE
    if page_w != PAGE_W:
        return {"ok": False, "errors": [f"[纸宽] 版式使用 {page_w}px，要求 {PAGE_W}px"]}
    want = {p.strip().lower() for p in (pages or "").split(",") if p.strip()}
    try:
        page_docs = split_pages(raw_html, html_path, page_w, paper)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    first_sid = page_docs[0][0] if page_docs else ""
    if want:
        found = {sid.lower() for sid, _ in page_docs}
        missing = sorted(want - found)
        if missing:
            return {"ok": False, "error": "missing pages: " + ", ".join(missing)}
        page_docs = [(sid, doc) for sid, doc in page_docs if sid.lower() in want]
    if not page_docs:
        return {"ok": False, "error": "no matching pages"}
    try:
        edge = find_edge()
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e)}
    exported: list[str] = []
    measure: list[dict] = []
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="layout-export-") as tmp:
        tmp_path = Path(tmp)
        for i, (sid, doc) in enumerate(page_docs, 1):
            src = tmp_path / f"{sid}.html"
            raw = tmp_path / f"{sid}.raw.png"
            src.write_text(doc, encoding="utf-8")
            try:
                screenshot(edge, src, raw, page_w, scale)
                errors.extend(f"{sid}: {error}" for error in inspect_page(
                    edge, src, page_w, scale, sid != first_sid))
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as e:
                return {"ok": False, "error": str(e)}
            dest = out_dir / f"{i:02d}_{sid.upper()}.png"
            if not raw.is_file():
                return {"ok": False, "error": f"screenshot failed: {sid}"}
            note = crop_sentinel(raw)
            if note:
                return {"ok": False, "error": f"{sid}: {note}"}
            proof = raw.read_bytes()
            dest.write_bytes(proof)
            exported.append(dest.name)
            with Image.open(dest) as png:
                w_px, h_px = png.size
            measure.append(
                {
                    "id": sid.lower(),
                    "page": dest.name,
                    "px": [w_px, h_px],
                    "ratio": round(h_px / w_px, 2) if w_px else None,
                    "sha256": hashlib.sha256(proof).hexdigest(),
                }
            )
    for m in measure:
        failure = dimension_error(*m["px"], scale)
        if failure:
            errors.append(f"{m['page']} {failure}")
    payload = {
        "ok": not errors,
        "errors": errors,
        "dir": str(out_dir).replace("\\", "/"),
        "n": len(exported),
        "pages": exported,
        "page_width_px": page_w,
        "scale": scale,
        "expect_png_width_px": PAGE_W * scale,
        "window_h_px": WINDOW_H,
        "measure": measure,
    }
    return payload


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", default="")
    parser.add_argument("--pages", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--width", type=int, default=0)
    parser.add_argument("--scale", type=int, default=0)
    parser.add_argument("--root", default="")
    args = parser.parse_args()
    root = Path(args.root).resolve() if args.root else Path.cwd()
    html_path = Path(args.html).resolve() if args.html else latest_html(root)
    payload = run(html_path, args.output, pages=args.pages, width=args.width, scale=args.scale)
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
