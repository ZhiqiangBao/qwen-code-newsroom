"""Newspaper copy via OpenAI-compatible /v1. Editor only packs by title/chars."""
from __future__ import annotations

import html
import json
import re
from datetime import date
from pathlib import Path

import api

KIND_CHARS = {"快讯": 220, "普通": 550, "深挖": 1400, "评论": 900}
KIND_HED = {"快讯": "s", "普通": "l", "深挖": "xl", "评论": "l"}
MAX_SLOTS = 20


def count_chars(text: str) -> int:
    text = re.sub(r"^---[\s\S]*?---\s*", "", text)
    han = len(re.findall(r"[\u4e00-\u9fff]", text))
    words = len(re.findall(r"[A-Za-z]+", text))
    nums = len(re.findall(r"\d+(?:\.\d+)?", text))
    return han + words + nums


def parse_front(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\n([\s\S]*?)\n---\n([\s\S]*)$", text)
    if not m:
        return {}, text.strip()
    meta = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        meta[k.strip()] = v.strip().strip('"')
    return meta, m.group(2).strip()


def extract_source(path: Path, title: str, limit: int = 3500) -> str:
    if not path.is_file():
        return ""
    raw = path.read_text(encoding="utf-8")
    keys = [w for w in re.split(r"[\s·，,：:]+", title) if len(w) >= 2]
    parts = re.split(r"\n(?=## )", raw)
    hit = []
    for p in parts:
        if any(k in p for k in keys[:6]):
            hit.append(p.strip())
    blob = "\n\n".join(hit) if hit else raw
    return blob[:limit]


def _prompt(title: str, line: str, kind: str, chars: int, source: str) -> list[dict]:
    sys = (
        "你是《星期时报》写稿员，不是主编。只根据素材写新闻正文。"
        "不许编造素材里没有的数字、引语、日期。没有的事实写「未获取」，不要补。"
        "每段至少有一个可核事实（日期、金额、人名、引语、位次）。"
        "第三人称。不要出现 A1/B2、desk/、rules/、子代理、取材过程。"
        "钱和百分比用阿拉伯数字。不要「不是A而是B」超过两次。"
        "只输出指定格式，不要解释。"
    )
    user = (
        f"线：{line}\n体裁：{kind}\n目标字数：约 {chars}\n标题（可微调，勿改事实）：{title}\n\n"
        f"素材（只许用这里的事实）：\n{source}\n\n"
        "按下面格式输出：\n"
        "---\n"
        "kicker: <眉题，如 人工智能 · 模型发布>\n"
        "hed: <见报标题>\n"
        "deck: <一两句导读，含关键数字>\n"
        "by: <本报综合　媒体名 日期>\n"
        "---\n\n"
        "<分段正文，段间空行>"
    )
    return [{"role": "system", "content": sys}, {"role": "user", "content": user}]


def write_copy(
    root: Path,
    stamp: str,
    slug: str,
    title: str,
    line: str,
    kind: str,
    source_path: str,
    chars: int | None = None,
) -> dict:
    kind = kind if kind in KIND_CHARS else "普通"
    target = chars or KIND_CHARS[kind]
    src = extract_source(root / source_path, title) if source_path else ""
    if not src:
        return {"ok": False, "error": "素材为空或路径不对", "source": source_path}
    resp = api.complete(_prompt(title, line, kind, target, src))
    if not resp.get("ok"):
        return resp
    text = (resp.get("text") or "").strip()
    meta, body = parse_front(text)
    if not body:
        body = text
    hed = meta.get("hed") or title
    kicker = meta.get("kicker") or line
    deck = meta.get("deck") or ""
    by = meta.get("by") or "本报综合"
    via = resp.get("via") or ""
    n = count_chars(body + hed + deck)
    dest = root / "desk" / "稿件" / stamp
    dest.mkdir(parents=True, exist_ok=True)
    md = (
        f"---\n"
        f"id: {slug}\n"
        f"line: {line}\n"
        f"kind: {kind}\n"
        f"kicker: {kicker}\n"
        f"hed: {hed}\n"
        f"deck: {deck}\n"
        f"by: {by}\n"
        f"via: {via}\n"
        f"source: {source_path}\n"
        f"chars: {n}\n"
        f"---\n\n{body.strip()}\n"
    )
    path = dest / f"{slug}.md"
    path.write_text(md, encoding="utf-8")
    return {
        "ok": True,
        "id": slug,
        "path": str(path.relative_to(root)).replace("\\", "/"),
        "hed": hed,
        "line": line,
        "kind": kind,
        "chars": n,
        "target": target,
        "via": via,
        "v1": resp.get("v1") or "",
    }


def pack(root: Path, stamp: str) -> dict:
    folder = root / "desk" / "稿件" / stamp
    items = []
    if folder.is_dir():
        for path in sorted(folder.rglob("*.md")):
            if path.name == "目录.json":
                continue
            meta, body = parse_front(path.read_text(encoding="utf-8"))
            items.append(
                {
                    "id": meta.get("id") or path.stem,
                    "hed": meta.get("hed") or path.stem,
                    "line": meta.get("line") or "",
                    "kind": meta.get("kind") or "普通",
                    "kicker": meta.get("kicker") or "",
                    "chars": int(meta.get("chars") or count_chars(body)),
                    "path": str(path.relative_to(root)).replace("\\", "/"),
                }
            )
    out = {"ok": True, "date": stamp, "n": len(items), "items": items, "total_chars": sum(i["chars"] for i in items)}
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "目录.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def copy_lineup(root: Path, stamp: str) -> dict:
    plan_path = root / "desk" / "版式" / f"{stamp}.json"
    if not plan_path.is_file():
        return {
            "ok": False,
            "error": "没有版式 json，主编或 makeup 先定槽",
            "path": str(plan_path.relative_to(root)).replace("\\", "/"),
        }
    lineup = json.loads(plan_path.read_text(encoding="utf-8"))
    slots = lineup.get("slots") or []
    if not slots:
        return {"ok": False, "error": "版式 slots 为空"}
    if len(slots) > MAX_SLOTS:
        return {"ok": False, "error": f"槽数 {len(slots)} 超过 {MAX_SLOTS}"}
    done = []
    for sl in slots:
        sid = str(sl.get("id") or "").strip()
        line = str(sl.get("line") or "").strip()
        source = str(sl.get("source") or "").strip()
        kind = str(sl.get("kind") or "普通").strip()
        title = str(sl.get("title") or sid)
        chars = sl.get("chars")
        if not sid or not line or not source:
            return {"ok": False, "error": f"槽缺 id/line/source: {sid or '?'}", "done": done}
        one = write_copy(root, stamp, sid, title, line, kind, source, int(chars) if chars else None)
        done.append(
            {
                "ok": bool(one.get("ok")),
                "id": sid,
                "path": one.get("path") or "",
                "chars": one.get("chars") or 0,
                "kind": kind,
                "error": one.get("error") or "",
            }
        )
        if not one.get("ok"):
            return {"ok": False, "error": one.get("error") or "copy failed", "id": sid, "done": done}
    packed = pack(root, stamp)
    return {"ok": True, "date": stamp, "n": len(done), "items": done, "total_chars": packed.get("total_chars") or 0}


def _paras(body: str) -> str:
    chunks = [html.escape(p.strip()) for p in re.split(r"\n\s*\n", body) if p.strip()]
    if not chunks:
        return ""
    first, rest = chunks[0], chunks[1:]
    bits = [f'<p class="lede drop">{first}</p>']
    bits.extend(f"<p>{p}</p>" for p in rest)
    return "\n".join(bits)


def render_article(meta: dict, body: str, lead: bool = False) -> str:
    kind = meta.get("kind") or "普通"
    hed_class = "xxl" if lead else KIND_HED.get(kind, "l")
    tag = "h2" if lead else "h3"
    kicker = html.escape(meta.get("kicker") or "")
    hed = html.escape(meta.get("hed") or "")
    deck = html.escape(meta.get("deck") or "")
    by = html.escape(meta.get("by") or "")
    if kind == "快讯":
        return (
            f'<article class="ni">\n<p class="kicker">{kicker}</p>\n'
            f'<{tag} class="hed {hed_class}">{hed}</{tag}>\n{_paras(body)}\n</article>'
        )
    head = f'<p class="kicker">{kicker}</p>\n<{tag} class="hed {hed_class}">{hed}</{tag}>\n'
    if deck:
        head += f'<p class="deck">{deck}</p>\n'
    if by:
        head += f'<p class="by">{by}</p>\n'
    if lead:
        return f'<div class="leadhead">\n{head}</div>\n<article>\n{_paras(body)}\n</article>'
    return f"<article>\n{head}{_paras(body)}\n</article>"


def compose(root: Path, stamp: str, lineup: dict | None = None) -> dict:
    packed = pack(root, stamp)
    by_id = {it["id"]: it for it in packed["items"]}
    if not by_id:
        return {"ok": False, "error": "没有稿件，先 desk.py copy"}
    plan_path = root / "desk" / "版式" / f"{stamp}.json"
    if lineup is None:
        if not plan_path.is_file():
            return {
                "ok": False,
                "error": "没有版式 json，主编或 makeup 先定槽",
                "path": str(plan_path.relative_to(root)).replace("\\", "/"),
            }
        lineup = json.loads(plan_path.read_text(encoding="utf-8"))
    pages = (lineup or {}).get("pages") or []
    if not pages:
        return {"ok": False, "error": "版式缺少 pages，禁止机械排版"}
    folder = root / "desk" / "稿件" / stamp
    bodies = {}
    metas = {}
    for it in packed["items"]:
        meta, body = parse_front((root / it["path"]).read_text(encoding="utf-8"))
        bodies[it["id"]] = body
        metas[it["id"]] = meta
    dt = date.fromisoformat(stamp)
    week = "日一二三四五六"[dt.weekday() + 1 if dt.weekday() < 6 else 0]
    # Monday Times: Monday is 一 in Chinese weekday with Monday=0 → 一
    week_map = "一二三四五六日"
    week = week_map[dt.weekday()]
    suffix = (lineup or {}).get("title_suffix") or (metas.get(pages[0].get("lead") or "", {}).get("hed") or "")
    nav = "".join(f'<a href="#{p["id"]}">{html.escape(p["label"])}</a>' for p in pages)
    chunks = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="UTF-8" />',
        '<meta name="viewport" content="width=device-width, initial-scale=1" />',
        f"<title>星期时报 · {dt.year} 年 {dt.month} 月 {dt.day} 日 · {html.escape(suffix)}</title>",
        '<link rel="preconnect" href="https://fonts.googleapis.com" />',
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />',
        '<link rel="stylesheet" href="css/site.css" />',
        "</head>",
        "<body>",
        f'<nav class="nav">\n{nav}\n</nav>',
    ]
    for i, page in enumerate(pages):
        flow = page.get("flow") or ""
        flow_cls = f' class="flow {flow}"'.replace("flow  ", "flow ") if flow else ' class="flow"'
        inner = []
        if page["id"] == "a1":
            inner.append(
                '<header class="mast">\n'
                '<div class="pre"><span>All the News That’s Fit to Print</span><span>星期时报</span></div>\n'
                "<hr />\n<div class=\"en\">The Monday Times</div>\n<h1>星期时报</h1>\n"
                '<hr class="dbl" />\n'
                f'<div class="date"><span>写稿 llama.cpp</span><span>{dt.year} 年 {dt.month} 月 {dt.day} 日　星期{week}</span><span>拼版 主编</span></div>\n'
                "<hr />\n</header>"
            )
        lead_id = page.get("lead") or ""
        arts = list(page.get("articles") or [])
        html_arts = []
        if lead_id and lead_id in bodies:
            html_arts.append(render_article(metas[lead_id], bodies[lead_id], lead=True))
        for aid in arts:
            if aid in bodies:
                html_arts.append(render_article(metas[aid], bodies[aid], lead=False))
        inner.append(f"<div{flow_cls}>\n" + "\n\n".join(html_arts) + "\n</div>")
        inner.append(f'<p class="folio">{page["id"].upper()}</p>')
        chunks.append(f'<section class="page" id="{page["id"]}">\n' + "\n".join(inner) + "\n</section>")
    chunks.append("</body></html>")
    out_html = root / f"{stamp}.html"
    out_html.write_text("\n".join(chunks) + "\n", encoding="utf-8")
    (folder / "目录.json").write_text(json.dumps(packed, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "html": str(out_html.name),
        "pages": [{"id": p["id"], "n": len(([p.get("lead")] if p.get("lead") else []) + (p.get("articles") or []))} for p in pages],
        "n_copy": packed["n"],
        "total_chars": packed["total_chars"],
        "catalog": str((folder / "目录.json").relative_to(root)).replace("\\", "/"),
    }
