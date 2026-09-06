"""星期时报脚本入口。经 MCP 服务器 desk 调用；不要用 shell 跑本目录。"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import catalog  # noqa: E402
from utf8io import dump  # noqa: E402

ROOT = catalog.ROOT


def _cfg(root: Path) -> dict:
    return catalog.load(root)


def _stamp(raw: str | None) -> str:
    return raw or date.today().isoformat()


def _dest(root: Path, stamp: str) -> Path:
    path = root / "desk" / "素材" / stamp
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_hot(args) -> dict:
    root = Path(args.root)
    stamp = _stamp(args.date)
    cfg = _cfg(root)
    rows = catalog.collect_hot(cfg)
    by_line = {k: [] for k in catalog.LINES}
    for it in rows:
        line = it.get("line")
        if line in by_line:
            by_line[line].append(it)
    out = {
        "ok": True,
        "cmd": "hot",
        "date": stamp,
        "n": len(rows),
        "headline_pool": catalog.headline_pool(rows),
        "by_line": {k: v[:20] for k, v in by_line.items()},
        "counts": {k: len(v) for k, v in by_line.items()},
    }
    dest = _dest(root, stamp)
    _write(dest / "榜单.json", out)
    return out


def cmd_feed(args) -> dict:
    root = Path(args.root)
    stamp = _stamp(args.date)
    line = args.line
    if line not in catalog.LINES:
        return {"ok": False, "error": f"unknown line {line}"}
    cfg = _cfg(root)
    start, end = catalog.window(stamp)
    rows = catalog.collect_feed(cfg, line, start, end)
    out = {
        "ok": True,
        "cmd": "feed",
        "date": stamp,
        "line": line,
        "window": {"start": start, "end": end},
        "n": len(rows),
        "items": rows[:40],
        "fetch_urls": [
            {
                "title": it.get("title"),
                "url": it.get("url"),
                "date": it.get("date"),
                "source": it.get("source"),
                "labs": it.get("labs") or [],
            }
            for it in rows
            if it.get("fetchable")
        ][:12],
        "labs": catalog.lab_status(rows, cfg, start, end),
    }
    dest = _dest(root, stamp)
    _write(dest / f"目录-{line}.json", out)
    return out


def cmd_quotes(args) -> dict:
    root = Path(args.root)
    stamp = _stamp(args.date)
    cfg = _cfg(root)
    data = catalog.quotes_tencent(cfg)
    data["cmd"] = "quotes"
    data["date"] = stamp
    dest = _dest(root, stamp)
    lines = [f"# 行情 · {stamp}", ""]
    if data.get("ok"):
        for row in data["rows"]:
            lines.append(
                f"- {row['name']} {row['code']} 收 {row['price']} 涨跌 {row['change']}（{row['pct']}%）"
            )
        lines.append("")
        lines.append(f"出处：{data.get('source')}")
    else:
        lines.append("未获取")
    (dest / "行情.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return data


def cmd_plan(args) -> dict:
    root = Path(args.root)
    stamp = _stamp(args.date)
    cfg = _cfg(root)
    start, end = catalog.window(stamp)
    hot_rows = catalog.collect_hot(cfg)
    by_line = {k: [] for k in catalog.LINES}
    for it in hot_rows:
        line = it.get("line")
        if line in by_line:
            by_line[line].append(it)
    feed_rows: list[dict] = []
    feeds = {}
    for line in catalog.LINES:
        items = catalog.collect_feed(cfg, line, start, end)
        feeds[line] = items[:25]
        feed_rows += items
        for it in items:
            if it.get("line") == line:
                by_line[line].append(it)
    quotes = catalog.quotes_tencent(cfg)
    labs = catalog.lab_status(hot_rows + feed_rows, cfg, start, end)
    out = {
        "ok": True,
        "cmd": "plan",
        "date": stamp,
        "window": {"start": start, "end": end},
        "headline_pool": catalog.headline_pool(hot_rows),
        "by_line": {k: v[:20] for k, v in by_line.items()},
        "feeds": feeds,
        "labs": labs,
        "fetch_urls": catalog.fetch_urls(by_line),
        "quotes": quotes,
        "hot_n": len(hot_rows),
        "feed_n": len(feed_rows),
    }
    dest = _dest(root, stamp)
    _write(dest / "线索.json", out)
    hot_by = {k: [] for k in catalog.LINES}
    for it in hot_rows:
        if it.get("line") in hot_by:
            hot_by[it["line"]].append(it)
    _write(
        dest / "榜单.json",
        {
            "ok": True,
            "date": stamp,
            "n": len(hot_rows),
            "headline_pool": out["headline_pool"],
            "by_line": {k: v[:20] for k, v in hot_by.items()},
            "counts": {k: len(v) for k, v in hot_by.items()},
        },
    )
    cmd_quotes(args)
    return out


def cmd_check(args) -> dict:
    cfg = _cfg(Path(args.root))
    rows = catalog.check_feeds(cfg)
    return {"ok": True, "cmd": "check", "n": len(rows), "feeds": rows}


def cmd_probe(args) -> dict:
    cfg = _cfg(Path(args.root))
    rows = catalog.probe(args.url, cfg)
    return {"ok": True, "cmd": "probe", "url": args.url, "tries": rows}


def cmd_serve(args) -> dict:
    import llama

    if args.probe:
        import api

        return api.status()
    return llama.serve()


def cmd_api(args) -> dict:
    import api

    return api.status()


def cmd_copy(args) -> dict:
    import copywrite

    if args.lineup:
        return copywrite.copy_lineup(Path(args.root), _stamp(args.date))
    missing = [n for n in ("id", "title", "line", "source") if not getattr(args, n, None)]
    if missing:
        return {"ok": False, "error": "需要 --lineup 或 " + ",".join("--" + n for n in missing)}
    return copywrite.write_copy(
        Path(args.root),
        _stamp(args.date),
        args.id,
        args.title,
        args.line,
        args.kind,
        args.source,
        args.chars,
    )


def cmd_pack(args) -> dict:
    import copywrite

    return copywrite.pack(Path(args.root), _stamp(args.date))


def cmd_compose(args) -> dict:
    import copywrite

    return copywrite.compose(Path(args.root), _stamp(args.date))


def cmd_review(args) -> dict:
    import review as layout_review

    stamp = _stamp(args.date)
    root = Path(args.root)
    html = root / f"{stamp}.html"
    out = root / "desk" / "版面" / stamp
    return layout_review.run(html, out, pages=args.pages or "", width=args.width or 0)


def cmd_materials(args) -> dict:
    stamp = _stamp(args.date)
    root = Path(args.root)
    folder = root / "desk" / "素材" / stamp
    files = []
    if folder.is_dir():
        for path in sorted(folder.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".md", ".json"}:
                continue
            rel = str(path.relative_to(root)).replace("\\", "/")
            kind = "快讯" if path.stem.endswith("-快讯") or path.name.endswith("-快讯.md") else "事件"
            if path.suffix == ".json":
                kind = "目录"
            files.append({"path": rel, "name": path.name, "kind": kind})
    return {"ok": True, "cmd": "materials", "date": stamp, "n": len(files), "files": files}


def main() -> None:
    p = argparse.ArgumentParser(description="星期时报取材")
    p.add_argument("--root", default=str(ROOT))
    sub = p.add_subparsers(dest="cmd", required=True)

    hot = sub.add_parser("hot", help="微博／百度／IT之家／豆瓣／B站")
    hot.add_argument("--date", default=None)
    hot.set_defaults(func=cmd_hot)

    feed = sub.add_parser("feed", help="一条线的 RSS／JSON，过滤取材窗口")
    feed.add_argument("--line", required=True)
    feed.add_argument("--date", default=None)
    feed.set_defaults(func=cmd_feed)

    quotes = sub.add_parser("quotes", help="腾讯行情")
    quotes.add_argument("--date", default=None)
    quotes.set_defaults(func=cmd_quotes)

    plan = sub.add_parser("plan", help="一期开工：热榜+四线目录+大厂命中+行情")
    plan.add_argument("--date", default=None)
    plan.set_defaults(func=cmd_plan)

    chk = sub.add_parser("check", help="ping feeds.json 里的源，死路跳过")
    chk.set_defaults(func=cmd_check)

    probe = sub.add_parser("probe", help="对域名试 /rss /feed 等路径")
    probe.add_argument("--url", required=True)
    probe.set_defaults(func=cmd_probe)

    srv = sub.add_parser("serve", help="启动第一写稿源 llama.cpp；端口被占自动换")
    srv.add_argument("--probe", action="store_true", help="探 /v1 端点，不拉模型")
    srv.set_defaults(func=cmd_serve)

    ap = sub.add_parser("api", help="探写稿 /v1 端点（llama.cpp 优先，再备用），不拉模型")
    ap.set_defaults(func=cmd_api)

    copy = sub.add_parser("copy", help="写一篇或 --lineup 填槽；stdout 无正文")
    copy.add_argument("--date", default=None)
    copy.add_argument("--lineup", action="store_true")
    copy.add_argument("--id", default=None)
    copy.add_argument("--title", default=None)
    copy.add_argument("--line", default=None)
    copy.add_argument("--kind", default="普通")
    copy.add_argument("--source", default=None, help="相对仓库根的素材路径")
    copy.add_argument("--chars", type=int, default=None)
    copy.set_defaults(func=cmd_copy)

    pack = sub.add_parser("pack", help="扫 desk/稿件/<日期>/ 写出目录.json")
    pack.add_argument("--date", default=None)
    pack.set_defaults(func=cmd_pack)

    comp = sub.add_parser("compose", help="按版式 json 拼 HTML；无 pages 则失败")
    comp.add_argument("--date", default=None)
    comp.set_defaults(func=cmd_compose)

    rev = sub.add_parser("review", help="见报 HTML 按版导出 PNG 并量尺")
    rev.add_argument("--date", default=None)
    rev.add_argument("--pages", default="")
    rev.add_argument("--width", type=int, default=0)
    rev.set_defaults(func=cmd_review)

    mats = sub.add_parser("materials", help="列出素材路径，不含正文")
    mats.add_argument("--date", default=None)
    mats.set_defaults(func=cmd_materials)

    args = p.parse_args()
    out = args.func(args)
    dump(out)


if __name__ == "__main__":
    main()
