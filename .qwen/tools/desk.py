"""星期时报脚本入口。经 MCP 服务器 desk 调用；不要用 shell 跑本目录。"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import catalog  # noqa: E402
import edition  # noqa: E402
from utf8io import dump  # noqa: E402

ROOT = catalog.ROOT


def _cfg(root: Path) -> dict:
    return catalog.load(root)


def _stamp(raw: str | None) -> str:
    return edition.issue_date(raw or date.today().isoformat()).isoformat()


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


def _urls_from_clue(clue: dict, line: str) -> list[dict]:
    keys = ("title", "url", "date", "source", "labs")
    out = []
    for it in clue.get("fetch_urls") or []:
        if it.get("line") != line:
            continue
        row = {k: it.get(k) for k in keys}
        row["labs"] = row.get("labs") or []
        out.append(row)
        if len(out) >= 12:
            break
    return out


def _hot_slice(items: list | None, line: str, limit: int = 12) -> list[dict]:
    names = {"微博热搜", "百度热搜", "百度财经", "百度电影", "百度电视剧"}
    out = []
    for it in items or []:
        if it.get("line") and it.get("line") != line:
            continue
        title = (it.get("title") or "").strip()
        if not title:
            continue
        src = it.get("source") or ""
        if it.get("role") != "clue" and src not in names:
            continue
        out.append(
            {"title": title, "source": src, "rank": it.get("rank"), "heat": it.get("heat")}
        )
        if len(out) >= limit:
            break
    return out


def _hot_for_line(dest: Path, clue: dict, line: str) -> list[dict]:
    board_path = dest / "榜单.json"
    if board_path.is_file():
        try:
            board = json.loads(board_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            board = {}
        by = (board.get("by_line") or {}).get(line) if isinstance(board, dict) else None
        hot = _hot_slice(by, line)
        if hot:
            return hot
    by = (clue.get("by_line") or {}).get(line) if isinstance(clue, dict) else None
    return _hot_slice(by, line)


def cmd_feed(args) -> dict:
    root = Path(args.root)
    stamp = _stamp(args.date)
    line = args.line
    if line not in catalog.LINES:
        return {"ok": False, "error": f"unknown line {line}"}
    dest = _dest(root, stamp)
    cfg = _cfg(root)
    start, end = catalog.window(stamp)
    _, feeds, statuses = catalog.collect_sources(cfg, dest / ".source-cache", start, end, (line,), False)
    rows = feeds[line]
    clue = {}
    try:
        clue = json.loads((dest / "线索.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if not isinstance(clue, dict):
        clue = {}
    hot = _hot_for_line(dest, clue, line)
    urls = catalog.fetch_urls({line: rows}, limit_each=12)
    for row in urls:
        row.pop("line", None)
    labs = catalog.lab_status(rows, cfg, start, end)
    out = {"ok": any(x["status"] in {"ok", "cached", "degraded"} for x in statuses), "cmd": "feed",
           "via": "sources", "date": stamp, "line": line,
           "window": {"start": start, "end": end, "end_exclusive": True},
           "n": len(rows), "fetch_urls": urls, "labs": labs, "labs_missing": labs["missing"],
           "hot": hot, "hot_n": len(hot), "sources": statuses,
           "clues": [{"title": row.get("title"), "source": row.get("source"), "url": row.get("url"),
                      "date_status": row.get("date_status")} for row in rows if row.get("role") == "clue"][:20],
           "catalog": f"desk/素材/{stamp}/目录-{line}.json"}
    _write(dest / f"目录-{line}.json", {**out, "items": rows[:40]})
    return out


def cmd_quotes(args) -> dict:
    root = Path(args.root)
    stamp = _stamp(args.date)
    cfg = _cfg(root)
    dest = _dest(root, stamp)
    previous = {}
    try:
        previous = json.loads((dest / "行情.json").read_text(encoding="utf-8")).get("by_source") or {}
    except (OSError, ValueError, AttributeError):
        pass
    if not previous:
        try:
            old_quotes = json.loads((dest / "线索.json").read_text(encoding="utf-8")).get("quotes") or {}
            previous = old_quotes.get("by_source") or {}
            if not previous:
                for name in ("tencent", "baidu"):
                    rows = [row for row in old_quotes.get("rows") or [] if row.get("via") == name]
                    if rows:
                        previous[name] = {"ok": True, "rows": rows,
                                          "source": (cfg.get("quotes") or {}).get(name, "")}
        except (OSError, ValueError, AttributeError, TypeError):
            pass
    data = catalog.quotes(cfg, previous)
    _write(dest / "行情.json", data)
    data["cmd"] = "quotes"
    data["date"] = stamp
    dest = _dest(root, stamp)
    lines = [f"# 行情 · {stamp}", ""]
    if data.get("ok"):
        for row in data["rows"]:
            via = row.get("via") or ""
            tag = f" · {via}" if via else ""
            if (data.get(via) or {}).get("reused"):
                tag += " · 沿用本期先前获取"
            lines.append(
                f"- {row['name']} {row['code']} 收 {row['price']} 涨跌 {row['change']}（{row['pct']}%）{tag}"
            )
        lines.append("")
        for src in data.get("sources") or [data.get("source")]:
            if src:
                lines.append(f"出处：{src}")
    else:
        lines.append("未获取")
    (dest / "行情.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return data


def cmd_plan(args) -> dict:
    root = Path(args.root)
    stamp = _stamp(args.date)
    cfg = _cfg(root)
    start, end = catalog.window(stamp)
    dest = _dest(root, stamp)
    hot_rows, feeds, statuses = catalog.collect_sources(cfg, dest / ".source-cache", start, end)
    by_line = {k: [] for k in catalog.LINES}
    for it in hot_rows:
        line = it.get("line")
        if line in by_line:
            by_line[line].append(it)
    feed_rows: list[dict] = []
    for line in catalog.LINES:
        items = feeds[line]
        feed_rows += items
        for it in items:
            if it.get("line") == line:
                by_line[line].append(it)
        by_line[line] = catalog.dedupe(by_line[line])
    quotes = cmd_quotes(args)
    labs = catalog.lab_status(hot_rows + feed_rows, cfg, start, end)
    out = {
        "ok": any(x["status"] in {"ok", "cached", "degraded"} for x in statuses) or bool(quotes.get("ok")),
        "cmd": "plan",
        "date": stamp,
        "window": {"start": start, "end": end, "end_exclusive": True},
        "sources": statuses,
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
    fetch_n = {}
    for line in catalog.LINES:
        fetch_n[line] = sum(1 for u in out["fetch_urls"] if u.get("line") == line)
    hit = (labs.get("hit") or {})
    return {
        "ok": out["ok"],
        "cmd": "plan",
        "date": stamp,
        "window": out["window"],
        "hot_n": out["hot_n"],
        "feed_n": out["feed_n"],
        "sources": statuses,
        "quotes_status": {name: quotes.get(name) for name in ("tencent", "baidu")},
        "quotes_n": len(quotes.get("rows") or []),
        "labs_missing": labs.get("missing") or [],
        "labs_hit_n": {k: len(v) for k, v in hit.items()},
        "fetch_n": fetch_n,
        "headline_pool": [
            {"title": it.get("title"), "line": it.get("line"), "rank": it.get("rank")}
            for it in (out.get("headline_pool") or [])[:12]
        ],
        "clue": f"desk/素材/{stamp}/线索.json",
    }


def cmd_collect(args) -> dict:
    root = Path(args.root)
    stamp = _stamp(args.date)
    start, end = catalog.window(stamp)
    _, feeds, statuses = catalog.collect_sources(_cfg(root), _dest(root, stamp) / ".source-cache",
                                                 start, end, include_hot=False)
    return {"ok": any(feeds.values()) or any(item["status"] in {"ok", "cached", "degraded"} for item in statuses),
            "date": stamp, "counts": {line: len(rows) for line, rows in feeds.items()}, "sources": statuses}


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


def cmd_ingest(args) -> dict:
    stamp = _stamp(args.date)
    line = (args.line or "").strip()
    kind = (args.kind or "").strip()
    title = (args.title or "").strip()
    body = (args.body or "").strip()
    body_file = (getattr(args, "body_file", None) or "").strip()
    if body_file:
        body = Path(body_file).read_text(encoding="utf-8").strip()
    if line not in catalog.LINES_ALL:
        return {"ok": False, "error": f"线名必须是 {'／'.join(catalog.LINES_ALL)}"}
    if kind not in {"深挖", "普通", "快讯", "补"}:
        return {"ok": False, "error": "kind 必须是 深挖／普通／快讯／补"}
    if not title or not body:
        return {"ok": False, "error": "need title,body"}
    url = (args.url or "").strip() or "未获取"
    day = (args.day or "").strip() or stamp
    note = (args.note or "").strip() or title
    pic = (args.pic or "").strip() or "无"
    folder = Path(args.root) / "desk" / "素材" / stamp / line
    stem = catalog.next_stem(folder, kind)
    path = folder / f"{stem}.md"
    if kind == "快讯":
        block = (
            f"## 快讯 · {title}\n"
            f"出处：{url}\n"
            f"日期：{day}\n"
            f"短讯：\n{body.strip()}\n"
        )
        if path.is_file():
            prev = path.read_text(encoding="utf-8").rstrip() + "\n\n"
        else:
            prev = f"# {line} · 快讯 · {stamp}\n\n"
        path.write_text(prev + block, encoding="utf-8")
        file_kind = "快讯"
    else:
        file_kind = "普通" if kind == "补" else kind
        text = (
            f"# {title}\n"
            f"线：{line}\n"
            f"性质：{file_kind}\n"
            f"出处：{url}\n"
            f"日期：{day}\n"
            f"要点：{note}\n"
            f"图片线索：{pic}\n"
            f"原文：\n{body.strip()}\n"
        )
        path.write_text(text, encoding="utf-8")
    rel = str(path.relative_to(Path(args.root))).replace("\\", "/")
    sid = f"{line}-{stem}"
    n_flash = catalog.flash_n(path.read_text(encoding="utf-8")) if file_kind == "快讯" else 0
    out = {
        "ok": True,
        "cmd": "ingest",
        "date": stamp,
        "line": line,
        "kind": file_kind,
        "id": sid,
        "path": rel,
        "source": rel,
        "title": title[:40],
    }
    if file_kind == "快讯":
        out["n_flash"] = n_flash
    return out


def _load_body(args) -> str:
    body = (getattr(args, "body", None) or "").strip()
    body_file = (getattr(args, "body_file", None) or "").strip()
    if body_file:
        body = Path(body_file).read_text(encoding="utf-8").strip()
    return body


def _page_ids(page: dict) -> list[str]:
    return [sid for sid in [page.get("lead"), *page.get("articles", []), *page.get("shorts", [])] if sid]


def _save_layout(root: Path, stamp: str, raw: str) -> dict:
    import copywrite

    data = json.loads(raw)
    if not isinstance(data, dict) or set(data) - {"pages", "figures", "title_suffix"}:
        raise ValueError("版式只接收 pages、figures 与 title_suffix")
    pages = data.get("pages")
    figures = data.get("figures", [])
    if not isinstance(pages, list) or not pages or not isinstance(figures, list):
        raise ValueError("版式须包含 pages 数组及可选的 figures 数组")
    stories = edition.load_evidence(root, stamp)
    packed = copywrite.pack(root, stamp)
    drafts = {item["id"]: item for item in packed["items"]}

    page_ids = set()
    placements = {}
    for page in pages:
        if not isinstance(page, dict):
            raise ValueError("每版须为对象")
        pid = page.get("id")
        if not isinstance(pid, str) or not re.fullmatch(r"[a-f][1-9][0-9]*", pid) or pid in page_ids:
            raise ValueError("版号无效或重复")
        page_ids.add(pid)
        if not isinstance(page.get("label"), str) or not page["label"].strip():
            raise ValueError(f"{pid} 缺少版名")
        if page.get("flow", "n2") not in {"n1", "n2", "n3"}:
            raise ValueError(f"{pid} 栏数只支持 n1、n2、n3")
        page.setdefault("flow", "n2")
        for key in ("articles", "shorts"):
            ids = page.setdefault(key, [])
            if not isinstance(ids, list) or any(not isinstance(sid, str) for sid in ids):
                raise ValueError(f"{pid} 的 {key} 须为稿件 ID 数组")
        if not isinstance(page.get("lead", ""), str) or not _page_ids(page):
            raise ValueError(f"{pid} 缺少有效稿件")
        for sid in _page_ids(page):
            if sid not in stories or sid not in drafts or sid in placements:
                raise ValueError(f"稿件未选、待写或重复上版：{sid}")
            placements[sid] = pid
        for sid in page["shorts"]:
            if stories[sid]["kind"] != "快讯":
                raise ValueError(f"快讯位只收快讯：{sid}")

    if pages[0].get("id") != "a1" or not pages[0].get("lead"):
        raise ValueError("首版须为 A1 并指定头条")
    edition.check_headline(stories[pages[0]["lead"]])
    if placements.keys() != stories.keys():
        missing = "、".join(stories.keys() - placements.keys())
        raise ValueError(f"入选稿件缺少版位：{missing}")

    figure_ids = set()
    for fig in figures:
        if not isinstance(fig, dict) or not isinstance(fig.get("id"), str) or not edition.ID.fullmatch(fig["id"]):
            raise ValueError("图位缺少有效 ID")
        sid = fig.get("article")
        if not isinstance(sid, str) or sid not in placements or fig["id"] in figure_ids:
            raise ValueError(f"图位未绑定入选稿件或 ID 重复：{fig['id']}")
        figure_ids.add(fig["id"])
        if fig.get("class", "wrap") not in {"wrap", "poster", "wide"}:
            raise ValueError(f"未知图位样式：{fig['id']}")
        fig["page"] = placements[sid]

    data["slots"] = [{"id": sid, "line": item["line"], "kind": item["kind"], "source": item["source"],
                      "chars": item["chars"], "copy_chars": item["chars"], "title": item["hed"]}
                     for sid, item in drafts.items()]
    path = root / "desk" / "版式" / f"{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    _write(path, data)
    return {"ok": True, "path": path.relative_to(root).as_posix(), "n_pages": len(pages),
            "n_slots": len(placements), "ids": list(placements)}


def cmd_put(args) -> dict:
    stamp = _stamp(args.date)
    kind = (args.kind or "").strip()
    raw = _load_body(args)
    root = Path(args.root)
    if not raw:
        return {"ok": False, "error": "need body"}
    if kind == "版式":
        return _save_layout(root, stamp, raw)
    if kind == "校对":
        dest = root / "desk" / "校对" / f"{stamp}.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        text = raw if raw.lstrip().startswith("#") else f"# 校对 {stamp}\n\n{raw}"
        dest.write_text(text.rstrip() + "\n", encoding="utf-8")
        n = sum(1 for ln in text.splitlines() if ln.strip().startswith("- ["))
        rel = str(dest.relative_to(root)).replace("\\", "/")
        return {"ok": True, "cmd": "put", "kind": "校对", "path": rel, "n": n}
    if kind == "版面":
        dest = root / "desk" / "版面" / stamp / "report.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        text = raw if raw.lstrip().startswith("#") else f"# 版面 {stamp}\n\n{raw}"
        dest.write_text(text.rstrip() + "\n", encoding="utf-8")
        rel = str(dest.relative_to(root)).replace("\\", "/")
        return {"ok": True, "cmd": "put", "kind": "版面", "path": rel}
    return {"ok": False, "error": "kind 必须是 版式／校对／版面"}


def cmd_copy(args) -> dict:
    import copywrite

    if args.lineup:
        return copywrite.copy_lineup(
            Path(args.root),
            _stamp(args.date),
            ids=getattr(args, "ids", "") or "",
            force=bool(getattr(args, "force", False)),
        )
    if getattr(args, "materials", False):
        return copywrite.copy_materials(
            Path(args.root),
            _stamp(args.date),
            ids=getattr(args, "ids", "") or "",
            force=bool(getattr(args, "force", False)),
        )
    missing = [n for n in ("id", "title", "line", "source") if not getattr(args, n, None)]
    if missing:
        return {"ok": False, "error": "需要 --lineup／--materials 或 " + ",".join("--" + n for n in missing)}
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


def cmd_select(args) -> dict:
    return edition.save_evidence(Path(args.root), _stamp(args.date), _load_body(args))


def cmd_prepare(args) -> dict:
    import publish as site

    return site.prepare(Path(args.root), _stamp(args.date))


def cmd_review(args) -> dict:
    import review as layout_review

    stamp = _stamp(args.date)
    root = Path(args.root)
    out = root / "desk" / "版面" / stamp
    candidate = out / "候选"
    manifest = candidate / "manifest.json"
    fingerprint = json.loads(manifest.read_text(encoding="utf-8"))["fingerprint"]
    result = layout_review.run(candidate / "index.html", out, pages=args.pages or "")
    result["fingerprint"] = fingerprint
    if not args.pages:
        current = json.loads(manifest.read_text(encoding="utf-8"))["fingerprint"]
        if current != fingerprint:
            return {"ok": False, "error": "量尺时候选已变化，请打开最新候选页"}
        _write(out / "layout.json", {"fingerprint": fingerprint, "result": result})
    return result


def cmd_publish(args) -> dict:
    import publish as site

    return site.run(Path(args.root), _stamp(args.date), approval=args.approve)


def _guess_line(path: Path, stem: str, header: str = "") -> str:
    if header in catalog.LINES_ALL:
        return header
    if path.parent.name in catalog.LINES_ALL:
        return path.parent.name
    for ln in sorted(catalog.LINES_ALL, key=len, reverse=True):
        if stem == ln or stem.startswith(ln + "-") or stem.startswith(ln + "·"):
            return ln
    return header if header in catalog.LINES_ALL else ""


def _material_label(path: Path) -> dict:
    name = path.name
    stem = path.stem
    kind = "事件"
    title = stem
    line = ""
    pic = ""
    if path.suffix.lower() == ".json" or name.startswith("目录-") or name in {"线索.json", "榜单.json"}:
        return {"kind": "目录", "title": stem, "line": "", "pic": ""}
    if name == "行情.md":
        return {"kind": "数据", "title": "行情", "line": "数据", "pic": ""}
    if catalog.STEM_RE.match(stem):
        if stem == "快讯":
            kind = "快讯"
        elif stem.startswith("深挖"):
            kind = "深挖"
        elif stem.startswith("补"):
            kind = "普通"
        else:
            kind = "普通"
    elif "-补" in stem:
        kind = "普通"
    try:
        head = path.read_text(encoding="utf-8")[:800]
    except OSError:
        head = ""
    header_line = ""
    for raw in head.splitlines():
        s = raw.strip()
        if s.startswith("# "):
            title = s[2:].strip()[:40]
            break
    for raw in head.splitlines():
        s = raw.strip()
        if s.startswith("性质："):
            kind = s.split("：", 1)[-1].strip() or kind
        elif s.startswith("线："):
            header_line = s.split("：", 1)[-1].strip()
        elif s.startswith("图片线索："):
            pic = s.split("：", 1)[-1].strip()
            if pic in {"无", "没有", "-"}:
                pic = ""
    line = _guess_line(path, stem, header_line)
    return {"kind": kind, "title": title, "line": line, "pic": pic[:120]}


def cmd_materials(args) -> dict:
    stamp = _stamp(args.date)
    root = Path(args.root)
    folder = root / "desk" / "素材" / stamp
    files = []
    skip = {"线索.json", "榜单.json"}
    if folder.is_dir():
        for path in sorted(folder.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".md", ".json"}:
                continue
            if path.name in skip or path.name.startswith("目录-"):
                continue
            rel = str(path.relative_to(root)).replace("\\", "/")
            lab = _material_label(path)
            raw = ""
            try:
                raw = path.read_text(encoding="utf-8") if path.suffix.lower() == ".md" else ""
            except OSError:
                raw = ""
            chars = catalog.count_chars(raw) if raw else 0
            n_flash = catalog.flash_n(raw) if (lab.get("kind") == "快讯" or path.stem == "快讯") else 0
            pic = lab.get("pic") or ""
            files.append(
                {
                    "path": rel,
                    "name": path.name,
                    "id": f"{lab.get('line')}-{path.stem}" if lab.get("line") else path.stem,
                    "kind": lab.get("kind") or "",
                    "line": lab.get("line") or "",
                    "title": lab.get("title") or "",
                    "chars": chars,
                    "suggest": catalog.suggest_chars(lab.get("kind") or "普通", n_flash),
                    "n_flash": n_flash,
                    "pic": pic if pic and pic not in {"无", "没有", "-"} else "",
                }
            )
    return {"ok": True, "cmd": "materials", "date": stamp, "n": len(files), "files": files}


def cmd_images(args) -> dict:
    stamp = _stamp(args.date)
    root = Path(args.root)
    folder = root / "img" / stamp
    files = []
    if folder.is_dir():
        for path in sorted(folder.iterdir()):
            if not path.is_file():
                continue
            rel = str(path.relative_to(root)).replace("\\", "/")
            files.append({"path": rel, "name": path.name, "kb": path.stat().st_size // 1024})
    return {"ok": True, "cmd": "images", "date": stamp, "n": len(files), "files": files}


def cmd_place(args) -> dict:
    stamp = _stamp(args.date)
    root = Path(args.root)
    src = Path(args.src)
    name = (args.name or src.name).replace("\\", "/").split("/")[-1]
    if not src.is_file():
        return {"ok": False, "error": "src missing", "src": str(src)}
    dest_dir = root / "img" / stamp
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    shutil.copyfile(src, dest)
    rel = str(dest.relative_to(root)).replace("\\", "/")
    return {"ok": True, "cmd": "place", "date": stamp, "path": rel, "kb": dest.stat().st_size // 1024}


def cmd_figure(args) -> dict:
    stamp = _stamp(args.date)
    root = Path(args.root)
    fid = (args.id or "").strip()
    src = str(args.src or "").replace("\\", "/").strip()
    if not fid or not src:
        return {"ok": False, "error": "need id,src"}
    path = root / "desk" / "版式" / f"{stamp}.json"
    if not path.is_file():
        return {"ok": False, "error": "没有版式 json", "path": f"desk/版式/{stamp}.json"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"ok": False, "error": "版式不是 JSON"}
    hit = None
    for fig in data.get("figures") or []:
        if str(fig.get("id") or "") == fid:
            fig["src"] = src
            hit = fig
            break
    if hit is None:
        return {"ok": False, "error": f"没有 figure id {fid}"}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rel = str(path.relative_to(root)).replace("\\", "/")
    return {"ok": True, "cmd": "figure", "path": rel, "id": fid, "src": src}


def _chars(text: str) -> int:
    return catalog.count_chars(text)


def _md_chars(path: Path) -> int:
    try:
        return _chars(path.read_text(encoding="utf-8"))
    except OSError:
        return 0


def _rel(root: Path, path: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def _empty_floor(kind: str, line: str = "") -> int:
    if line == "数据" or kind == "数据":
        return 20
    return {"深挖": 120, "普通": 60, "快讯": 30, "补": 60, "稿件": 80, "校对": 10, "版面": 10}.get(kind, 40)


def _landed_one(root: Path, rel: str) -> dict:
    rel = str(rel or "").replace("\\", "/").strip()
    path = root / rel
    if not path.is_file():
        return {"ok": False, "path": rel, "missing": True, "chars": 0, "kb": 0}
    kb = path.stat().st_size // 1024
    suf = path.suffix.lower()
    if suf in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        empty = path.stat().st_size < 100
        return {"ok": not empty, "path": rel, "chars": 0, "kb": kb, "empty": empty}
    if suf == ".json":
        raw = path.read_text(encoding="utf-8")
        try:
            json.loads(raw)
            valid = True
        except json.JSONDecodeError:
            valid = False
        chars = _chars(raw)
        empty = (not raw.strip()) or not valid
        return {"ok": not empty, "path": rel, "chars": chars, "kb": kb, "empty": empty, "json": valid}
    chars = _md_chars(path)
    empty = chars < 20
    return {"ok": not empty, "path": rel, "chars": chars, "kb": kb, "empty": empty}


def _landed_clue(root: Path, stamp: str) -> dict:
    dest = root / "desk" / "素材" / stamp
    items = []
    missing = []
    empty = []
    for name, keys in (
        ("线索.json", ("fetch_urls", "by_line")),
        ("榜单.json", ("n", "by_line")),
        ("行情.md", ()),
    ):
        path = dest / name
        rel = f"desk/素材/{stamp}/{name}"
        if not path.is_file():
            missing.append(rel)
            continue
        if name.endswith(".json"):
            try:
                raw = path.read_text(encoding="utf-8")
                data = json.loads(raw)
            except (OSError, json.JSONDecodeError):
                empty.append({"path": rel, "chars": 0})
                continue
            n = 0
            if "fetch_urls" in keys:
                n = len(data.get("fetch_urls") or [])
            elif "n" in data:
                n = int(data.get("n") or 0)
            chars = _chars(raw)
            row = {"path": rel, "chars": chars, "n": n}
            items.append(row)
            if chars < 20 or (name == "线索.json" and n == 0):
                empty.append(row)
        else:
            chars = _md_chars(path)
            row = {"path": rel, "chars": chars}
            items.append(row)
            if chars < _empty_floor("数据"):
                empty.append(row)
    return {
        "ok": not missing and not empty,
        "kind": "线索",
        "n": len(items),
        "total_chars": sum(it.get("chars") or 0 for it in items),
        "items": items,
        "missing": missing,
        "empty": empty,
    }


def _landed_materials(root: Path, stamp: str, line: str = "") -> dict:
    mats = cmd_materials(argparse.Namespace(root=str(root), date=stamp, cmd="materials"))
    files = []
    empty = []
    by_line = {k: {"n": 0, "chars": 0} for k in catalog.LINES_ALL}
    for it in mats.get("files") or []:
        if line and it.get("line") != line:
            continue
        path = root / it["path"]
        kind = it.get("kind") or ""
        ln = it.get("line") or ""
        chars = _md_chars(path) if path.is_file() else 0
        sid = f"{ln}-{path.stem}" if ln and path.suffix.lower() == ".md" else path.stem
        row = {
            "path": it["path"],
            "id": sid,
            "line": ln,
            "kind": kind,
            "title": it.get("title") or "",
            "chars": chars,
        }
        files.append(row)
        if ln in by_line:
            by_line[ln]["n"] += 1
            by_line[ln]["chars"] += chars
        floor = _empty_floor(kind, ln)
        if not path.is_file() or chars < floor:
            empty.append(row)
    if line:
        by_line = {line: by_line.get(line) or {"n": 0, "chars": 0}}
        missing_lines = [line] if by_line[line]["n"] == 0 else []
    else:
        missing_lines = [k for k in catalog.LINES_ALL if by_line[k]["n"] == 0]
    return {
        "ok": not empty and not missing_lines,
        "kind": "素材",
        "n": len(files),
        "total_chars": sum(it["chars"] for it in files),
        "by_line": by_line,
        "missing_lines": missing_lines,
        "empty": empty,
        "items": files,
    }


def _load_lineup(root: Path, stamp: str) -> tuple[dict | None, str]:
    path = root / "desk" / "版式" / f"{stamp}.json"
    rel = f"desk/版式/{stamp}.json"
    if not path.is_file():
        alt = root / "desk" / "版式" / f"{stamp}.md"
        if alt.is_file():
            return None, f"desk/版式/{stamp}.md（需要 json）"
        return None, rel
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None, rel
    if not isinstance(data, dict):
        return None, rel
    return data, rel


def _landed_layout(root: Path, stamp: str) -> dict:
    data, rel = _load_lineup(root, stamp)
    missing = []
    empty = []
    if data is None:
        return {
            "ok": False,
            "kind": "版式",
            "path": rel,
            "n_pages": 0,
            "n_slots": 0,
            "ids": [],
            "missing": [rel],
            "empty": [],
            "source_missing": [],
        }
    slots = data.get("slots") or []
    pages = data.get("pages") or []
    ids = [str(s.get("id") or "") for s in slots]
    source_missing = []
    if not slots or not pages:
        missing.append(rel)
    return {
        "ok": not missing and not empty and not source_missing,
        "kind": "版式",
        "path": rel,
        "chars": _chars(json.dumps(data, ensure_ascii=False)),
        "n_pages": len(pages),
        "n_slots": len(slots),
        "ids": ids,
        "shorts": {p.get("id"): list(p.get("shorts") or []) for p in pages},
        "missing": missing,
        "empty": empty,
        "source_missing": source_missing,
    }


def _landed_copy(root: Path, stamp: str) -> dict:
    folder = root / "desk" / "稿件" / stamp
    items = []
    empty = []
    if folder.is_dir():
        for path in sorted(folder.glob("*.md")):
            chars = _md_chars(path)
            rel = _rel(root, path)
            row = {"path": rel, "id": path.stem, "chars": chars}
            items.append(row)
            if chars < _empty_floor("稿件"):
                empty.append(row)
    data, _ = _load_lineup(root, stamp)
    slot_ids = [str(s.get("id") or "") for s in (data.get("slots") or [])] if data else []
    have = {it["id"] for it in items}
    missing = [sid for sid in slot_ids if sid and sid not in have]
    return {
        "ok": not empty and not missing and (bool(items) if not slot_ids else True),
        "kind": "稿件",
        "n": len(items),
        "total_chars": sum(it["chars"] for it in items),
        "ids": [it["id"] for it in items],
        "missing": missing,
        "empty": empty,
        "items": items,
    }


def _landed_proof(root: Path, stamp: str) -> dict:
    path = root / "desk" / "校对" / f"{stamp}.md"
    rel = f"desk/校对/{stamp}.md"
    if not path.is_file():
        return {
            "ok": False,
            "kind": "校对",
            "path": rel,
            "chars": 0,
            "n": 0,
            "tags": [],
            "missing": [rel],
            "empty": [],
        }
    text = path.read_text(encoding="utf-8")
    chars = _chars(text)
    tags = []
    for ln in text.splitlines():
        m = re.match(r"-\s*\[([^\]]+)\]", ln.strip())
        if m:
            tags.append(m.group(1))
    empty = [{"path": rel, "chars": chars}] if chars < _empty_floor("校对") else []
    return {
        "ok": not empty,
        "kind": "校对",
        "path": rel,
        "chars": chars,
        "n": len(tags),
        "tags": tags,
        "missing": [],
        "empty": empty,
    }


def _landed_pages(root: Path, stamp: str) -> dict:
    folder = root / "desk" / "版面" / stamp
    report = folder / "report.md"
    rel = f"desk/版面/{stamp}/report.md"
    missing = []
    empty = []
    chars = 0
    if not report.is_file():
        missing.append(rel)
    else:
        chars = _md_chars(report)
        if chars < _empty_floor("版面"):
            empty.append({"path": rel, "chars": chars})
    pngs = []
    if folder.is_dir():
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() != ".png":
                continue
            kb = path.stat().st_size // 1024
            row = {"path": _rel(root, path), "kb": kb}
            pngs.append(row)
            if path.stat().st_size < 100:
                empty.append(row)
    return {
        "ok": not missing and not empty,
        "kind": "版面",
        "path": rel,
        "chars": chars,
        "n_png": len(pngs),
        "pngs": pngs,
        "missing": missing,
        "empty": empty,
    }


def _landed_images(root: Path, stamp: str) -> dict:
    folder = root / "img" / stamp
    items = []
    empty = []
    if folder.is_dir():
        for path in sorted(folder.iterdir()):
            if not path.is_file():
                continue
            kb = path.stat().st_size // 1024
            row = {"path": _rel(root, path), "kb": kb}
            items.append(row)
            if path.stat().st_size < 100:
                empty.append(row)
    return {
        "ok": not empty,
        "kind": "图",
        "n": len(items),
        "items": items,
        "empty": empty,
        "missing": [],
    }


def cmd_landed(args) -> dict:
    stamp = _stamp(args.date)
    root = Path(args.root)
    kind = (getattr(args, "kind", None) or "全部").strip() or "全部"
    line = (getattr(args, "line", None) or "").strip()
    path = (getattr(args, "path", None) or "").strip()
    if path:
        one = _landed_one(root, path)
        one["cmd"] = "landed"
        one["date"] = stamp
        return one
    runners = {
        "线索": lambda: _landed_clue(root, stamp),
        "素材": lambda: _landed_materials(root, stamp, line),
        "版式": lambda: _landed_layout(root, stamp),
        "稿件": lambda: _landed_copy(root, stamp),
        "校对": lambda: _landed_proof(root, stamp),
        "版面": lambda: _landed_pages(root, stamp),
        "图": lambda: _landed_images(root, stamp),
    }
    if kind != "全部" and kind not in runners:
        return {"ok": False, "error": "kind 必须是 线索／素材／版式／稿件／校对／版面／图／全部"}
    if kind != "全部":
        out = runners[kind]()
        out["cmd"] = "landed"
        out["date"] = stamp
        return out
    parts = {name: fn() for name, fn in runners.items()}
    return {
        "ok": all(p.get("ok") for p in parts.values()),
        "cmd": "landed",
        "date": stamp,
        "kind": "全部",
        **parts,
    }


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

    collect = sub.add_parser("collect", help="为下一期增量积累固定来源线索")
    collect.add_argument("--date", required=True)
    collect.set_defaults(func=cmd_collect)

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
    copy.add_argument("--materials", action="store_true", help="按入选证据写稿，再生成稿件目录")
    copy.add_argument("--id", default=None)
    copy.add_argument("--title", default=None)
    copy.add_argument("--line", default=None)
    copy.add_argument("--kind", default="普通")
    copy.add_argument("--source", default=None, help="相对仓库根的素材路径")
    copy.add_argument("--chars", type=int, default=None)
    copy.add_argument("--ids", default="", help="只重写这些槽 id，逗号分隔")
    copy.add_argument("--force", action="store_true", help="已有成稿也重写")
    copy.set_defaults(func=cmd_copy)

    ing = sub.add_parser("ingest", help="取材落盘：自动编号 深挖-01／普通-01／快讯／补-1")
    ing.add_argument("--date", default=None)
    ing.add_argument("--line", required=True)
    ing.add_argument("--kind", required=True, help="深挖|普通|快讯|补")
    ing.add_argument("--title", required=True)
    ing.add_argument("--body", default="")
    ing.add_argument("--body-file", default="", dest="body_file")
    ing.add_argument("--url", default="")
    ing.add_argument("--day", default="")
    ing.add_argument("--note", default="")
    ing.add_argument("--pic", default="")
    ing.set_defaults(func=cmd_ingest)

    putp = sub.add_parser("put", help="落盘版式 json／校对 md／版面 report.md")
    putp.add_argument("--date", default=None)
    putp.add_argument("--kind", required=True, help="版式|校对|版面")
    putp.add_argument("--body", default="")
    putp.add_argument("--body-file", default="", dest="body_file")
    putp.set_defaults(func=cmd_put)

    pack = sub.add_parser("pack", help="扫 desk/稿件/<日期>/ 写出目录.json")
    pack.add_argument("--date", default=None)
    pack.set_defaults(func=cmd_pack)

    comp = sub.add_parser("compose", help="按版式 json 拼 HTML；无 pages 则失败")
    comp.add_argument("--date", default=None)
    comp.set_defaults(func=cmd_compose)

    select = sub.add_parser("select", help="核对并保存本期入选稿件的证据表")
    select.add_argument("--date", required=True)
    select.add_argument("--body-file", required=True)
    select.set_defaults(func=cmd_select)

    prepare = sub.add_parser("prepare", help="生成可审阅的发布候选页")
    prepare.add_argument("--date", required=True)
    prepare.set_defaults(func=cmd_prepare)

    rev = sub.add_parser("review", help="候选页按版导出 PNG 并量尺")
    rev.add_argument("--date", default=None)
    rev.add_argument("--pages", default="")
    rev.set_defaults(func=cmd_review)

    mats = sub.add_parser("materials", help="列出素材路径，不含正文")
    mats.add_argument("--date", default=None)
    mats.set_defaults(func=cmd_materials)

    pub = sub.add_parser("publish", help="核对候选指纹后更新 docs/")
    pub.add_argument("--date", required=True)
    pub.add_argument("--approve", required=True)
    pub.set_defaults(func=cmd_publish)

    imgs = sub.add_parser("images", help="列出 img/<日期>/ 文件名，不含像素")
    imgs.add_argument("--date", default=None)
    imgs.set_defaults(func=cmd_images)

    plc = sub.add_parser("place", help="把一张图拷进 img/<日期>/")
    plc.add_argument("--date", default=None)
    plc.add_argument("--src", required=True)
    plc.add_argument("--name", default="")
    plc.set_defaults(func=cmd_place)

    fig = sub.add_parser("figure", help="把 img 路径写入版式 figures[].src，不改正文")
    fig.add_argument("--date", default=None)
    fig.add_argument("--id", required=True)
    fig.add_argument("--src", required=True)
    fig.set_defaults(func=cmd_figure)

    land = sub.add_parser("landed", help="主编核验落盘：空文件／缺文件／字数，无正文")
    land.add_argument("--date", default=None)
    land.add_argument("--kind", default="全部", help="线索|素材|版式|稿件|校对|版面|图|全部")
    land.add_argument("--line", default="", help="仅素材：数据|人工智能|科技|娱乐|动漫")
    land.add_argument("--path", default="", help="只核这一条相对路径")
    land.set_defaults(func=cmd_landed)

    args = p.parse_args()
    try:
        out = args.func(args)
    except (OSError, ValueError) as exc:
        out = {"ok": False, "error": str(exc)}
    dump(out)
    if not out.get("ok", False):
        sys.exit(1)


if __name__ == "__main__":
    main()
