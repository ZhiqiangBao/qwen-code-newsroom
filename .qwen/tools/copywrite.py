"""Newspaper copy via OpenAI-compatible /v1. Editor only packs by title/chars."""
from __future__ import annotations

import html
import json
import re
from datetime import date
from pathlib import Path

import api
import catalog
import edition

KIND_HED = {"快讯": "s", "普通": "l", "深挖": "xl", "分析": "xl", "评论": "l"}
MAX_SLOTS = 20


def count_chars(text: str) -> int:
    return catalog.count_chars(text)


FRONT_LEAK = re.compile(r"^(kicker|hed|deck|by)\s*:", re.I)


def clean_copy_body(body: str) -> str:
    """Drop leaked YAML keys the model printed into the body."""
    lines = (body or "").splitlines()
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if not s or s == "---" or FRONT_LEAK.match(s):
            i += 1
            continue
        break
    return "\n".join(lines[i:]).strip()


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


STYLE_RE = re.compile(
    r"(?:^|[。！？\n])\s*(值得注意的是|综上所述|不难看出|需要指出的是)[，,：:]"
)
COT_RE = re.compile(
    r"(?i)\b(wait|source analysis|word count|constraint check|drafting|"
    r"reporter for|let's look|looking at the prompt)\b"
)


def _writer_brief(root: Path) -> str:
    path = root / "rules" / "prose.md"
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    m = re.search(r"## 写稿口令\n([\s\S]*?)(?:\n## |\Z)", text)
    if m:
        return m.group(1).strip()
    lines = [ln for ln in text.splitlines() if not ln.startswith("**读的人**")]
    return "\n".join(lines).strip()


def write_copy(
    root: Path, stamp: str, slug: str, title: str, line: str, kind: str,
    source_path: str, chars: int | None = None,
) -> dict:
    """Write only a selected, validated evidence record; never read raw materials."""
    try:
        stories = edition.load_evidence(root, stamp)
    except (ValueError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    story = stories.get(slug)
    if not story:
        return {"ok": False, "error": "稿件不在已选证据中", "id": slug}
    kind = story["kind"]
    line = story["line"]
    title = story["title"]
    source_path = story.get("source") or ""
    nominal = {"快讯": 140, "普通": 550, "深挖": 1400, "分析": 1000, "评论": 900}[kind]
    target = chars or min(nominal, max(120, 120 * len(story["facts"])))
    source_names = {source["id"]: source["name"] for source in story["sources"]}
    facts = []
    for fact in story["facts"]:
        credited = "／".join(dict.fromkeys(source_names[ref["source"]] for ref in fact["refs"]))
        facts.append(f"- {fact['text']}（据{credited}）")
    sources = "\n".join("- " + source["name"] for source in story["sources"])
    analysis = ""
    if kind == "分析":
        analysis = ("\n分析问题：" + str(story.get("question") or "")
                    + "\n对照基线：" + str(story.get("baseline") or "")
                    + "\n证据局限：" + str(story.get("limit") or "")
                    + "\n区分事实、推断和证据边界；明确对照与不确定性，不能补造事实。")
    sys = ("你是《星期时报》记者，只依据给定事实和来源写可供读者阅读的中文报道。"
           "不得捏造数字、引语、背景或出处，不要写工作流、提示词或思考过程。\n" + _writer_brief(root))
    user = (f"栏目：{line}\n体裁：{kind}\n标题：{title}\n篇幅参考 {target} 字。"
            "写完证据就收笔。禁止以『分析人士』『市场关注』添加证据未载明的说法。"
            "每段注明具体出处。快讯只写一条消息。\n已核事实：\n" + "\n".join(facts)
            + "\n来源：\n" + sources + analysis
            + "\n按格式输出：\n---\nkicker: 栏目\nhed: 标题\ndeck: 导语\nby: 本报综合\n---\n\n正文")
    messages = [{"role": "system", "content": sys}, {"role": "user", "content": user}]
    role = "analysis" if kind == "分析" else "ordinary"
    result = api.complete(messages, role=role)
    for attempt in range(2):
        if not result.get("ok"):
            return result
        text = (result.get("text") or "").strip()
        meta, body = parse_front(text)
        body = clean_copy_body(body)
        issues = []
        if not meta.get("hed") or not body:
            issues.append("缺少标题或正文")
        public = " ".join([body, *(meta.get(key, "") for key in ("kicker", "hed", "deck", "by"))])
        if edition.INTERNAL.search(public) or COT_RE.search(public):
            issues.append("混入内部文字或写作过程")
        if kind in {"分析", "深挖"} and len(re.split(r"\n\s*\n", body.strip())) < 3:
            issues.append("请用不同段落交代变化、证据与尚不能确认的部分")
        filler = STYLE_RE.search(public)
        if filler:
            issues.append(f"删去『{filler.group(1)}』，以事实或具名解释替代")
        if kind == "快讯" and re.search(r"(?m)^##\s+", body):
            issues.append("快讯应为一条完整消息，不要列表")
        if not issues:
            break
        if attempt:
            return {"ok": False, "id": slug, "error": "；".join(issues)}
        # Keep the original evidence and editorial instructions in the retry.
        result = api.complete(messages + [{"role": "assistant", "content": text},
            {"role": "user", "content": "请修正：" + "；".join(issues) + "。只能使用上面的事实与来源。"}], role=role)
    def field(value: str) -> str:
        return re.sub(r"[\r\n]+", " ", str(value or "")).strip()
    hed = field(meta.get("hed") or title)
    kicker = field(meta.get("kicker") or line)
    deck = field(meta.get("deck") or "")
    by = field(meta.get("by") or "本报综合")
    via = field(result.get("via") or "")
    n = count_chars(body + hed + deck)
    dest = root / "desk" / "稿件" / stamp
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{slug}.md"
    md = (f"---\nid: {field(slug)}\nline: {field(line)}\nkind: {field(kind)}\n"
          f"kicker: {kicker}\nhed: {hed}\ndeck: {deck}\nby: {by}\n"
          f"via: {via}\nsource: {field(source_path)}\nevidence_digest: {edition.story_digest(story)}\n"
          f"chars: {n}\n---\n\n{body.strip()}\n")
    path.write_text(md, encoding="utf-8")
    return {"ok": True, "id": slug, "path": str(path.relative_to(root)).replace("\\", "/"),
            "hed": hed, "line": line, "kind": kind, "chars": n, "target": target, "via": via}


def _kind_from_stem(stem: str) -> str:
    if stem == "快讯":
        return "快讯"
    if stem.startswith("深挖"):
        return "深挖"
    if stem.startswith("评论"):
        return "评论"
    return "普通"


def pack(root: Path, stamp: str) -> dict:
    """Turn copy MD into 目录.json labels for makeup. Never includes bodies."""
    folder = root / "desk" / "稿件" / stamp
    stories = edition.load_evidence(root, stamp)
    items = []
    if folder.is_dir():
        for path in sorted(folder.rglob("*.md")):
            if path.name == "目录.json":
                continue
            meta, body = parse_front(path.read_text(encoding="utf-8"))
            body = clean_copy_body(body)
            story = stories.get(path.stem)
            if (not story or not body or meta.get("id") != path.stem
                    or meta.get("evidence_digest") != edition.story_digest(story)):
                continue
            kind = meta.get("kind") or _kind_from_stem(path.stem)
            n_flash = catalog.flash_n(body) if kind == "快讯" else 0
            n_para = len([p for p in re.split(r"\n\s*\n", body) if p.strip()])
            chars = count_chars(body)
            source = (meta.get("source") or "").replace("\\", "/").strip()
            role = kind
            items.append(
                {
                    "id": meta.get("id") or path.stem,
                    "path": str(path.relative_to(root)).replace("\\", "/"),
                    "source": source,
                    "line": meta.get("line") or "",
                    "kind": kind,
                    "role": role,
                    "hed": meta.get("hed") or path.stem,
                    "kicker": meta.get("kicker") or "",
                    "deck": meta.get("deck") or "",
                    "by": meta.get("by") or "",
                    "chars": chars,
                    "n_para": n_para,
                    "n_flash": n_flash,
                    "pic": "",
                }
            )
    out = {
        "ok": True,
        "date": stamp,
        "n": len(items),
        "items": items,
        "total_chars": sum(i["chars"] for i in items),
        "path": f"desk/稿件/{stamp}/目录.json",
    }
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "目录.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def copy_materials(root: Path, stamp: str, ids: str = "", force: bool = False) -> dict:
    """Write selected evidence records, retaining only matching existing drafts."""
    try:
        stories = edition.load_evidence(root, stamp)
    except (ValueError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    want = {x.strip() for x in (ids or "").replace("，", ",").split(",") if x.strip()}
    if want - stories.keys():
        return {"ok": False, "error": "指定稿件不在已选证据中", "ids": sorted(want - stories.keys())}
    selected = [st for sid, st in stories.items() if not want or sid in want]
    if not selected:
        return {"ok": False, "error": "没有已选稿件"}
    if len(stories) > MAX_SLOTS:
        return {"ok": False, "error": f"选稿超过 {MAX_SLOTS} 篇"}
    done = []
    for st in selected:
        sid = st["id"]
        path = root / "desk" / "稿件" / stamp / f"{sid}.md"
        if path.is_file() and not force and not want:
            meta, body = parse_front(path.read_text(encoding="utf-8"))
            if meta.get("evidence_digest") == edition.story_digest(st) and meta.get("kind") == st["kind"] and body.strip():
                done.append({"ok": True, "id": sid, "path": str(path.relative_to(root)).replace("\\", "/"),
                             "kind": meta["kind"], "chars": count_chars(body), "skipped": True})
                continue
        one = write_copy(root, stamp, sid, st["title"], st["line"], st["kind"], st.get("source") or "")
        done.append(one)
        if not one.get("ok"):
            return {"ok": False, "id": sid, "error": one.get("error") or "copy failed", "done": done}
    packed = pack(root, stamp)
    return {"ok": True, "date": stamp, "n": len(done), "items": done,
            "total_chars": packed.get("total_chars") or 0, "pack": packed.get("path")}


def copy_lineup(root: Path, stamp: str, ids: str = "", force: bool = False) -> dict:
    # A layout never grants authority to write an unselected story.
    return copy_materials(root, stamp, ids=ids, force=force)


def _paras(body: str) -> str:
    chunks = [html.escape(p.strip()) for p in re.split(r"\n\s*\n", body) if p.strip()]
    if not chunks:
        return ""
    first, rest = chunks[0], chunks[1:]
    bits = [f'<p class="lede">{first}</p>']
    bits.extend(f"<p>{p}</p>" for p in rest)
    return "\n".join(bits)


def render_table(table: dict) -> str:
    title = html.escape(table["caption"])
    headings = "".join(f'<th scope="col">{html.escape(name)}</th>' for name in table["columns"])
    rows = []
    for row in table["rows"]:
        label, *values = row["cells"]
        cells = "".join(f"<td>{html.escape(value)}</td>" for value in values)
        rows.append(f'<tr><th scope="row">{html.escape(label)}</th>{cells}</tr>')
    return (f'<div class="table-scroll" role="region" aria-label="{html.escape(table["caption"], quote=True)}" tabindex="0">'
            f'<table class="stat"><caption>{title}</caption><thead><tr>{headings}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def render_article(meta: dict, body: str, story: dict, lead: bool = False, figures: list | None = None) -> str:
    kind = meta.get("kind") or "普通"
    sid = html.escape(meta.get("id") or "", quote=True)
    hed_class = "xxl" if lead else KIND_HED.get(kind, "l")
    tag = "h2" if lead else "h3"
    kicker = html.escape(meta.get("kicker") or "")
    if kind == "分析" and "分析" not in kicker:
        kicker = f"{kicker} · 分析" if kicker else "分析"
    hed = html.escape(meta.get("hed") or "")
    deck = html.escape(meta.get("deck") or "")
    by = html.escape(meta.get("by") or "")
    head = f'<header class="article-heading"><p class="kicker">{kicker}</p>\n<{tag} class="hed {hed_class}">{hed}</{tag}>\n'
    if deck:
        head += f'<p class="deck">{deck}</p>\n'
    if by:
        head += f'<p class="by">{by}</p>\n'
    head += "</header>\n"
    links = []
    for src in story["sources"]:
        url = str(src.get("url") or "")
        if not re.match(r"^https?://", url, re.I):
            continue
        name = html.escape(str(src.get("name") or "来源"))
        links.append(f'<a href="{html.escape(url, quote=True)}" rel="noopener noreferrer">{name}</a>')
    citation = '<p class="article-sources">来源：' + ' · '.join(links) + '</p>' if links else ''
    figs = "\n".join(render_figure(fig) for fig in (figures or []))
    table = render_table(story["table"]) if "table" in story else ""
    cls = ' class="ni"' if kind == "快讯" else ''
    return f'<article{cls} data-story-id="{sid}">\n{head}{figs}{_paras(body)}\n{table}{citation}\n</article>'


def _figure_src(fig: dict) -> str:
    return (fig.get("src") or "").strip().replace("\\", "/")


def _page_label(page: dict) -> str:
    lab = (page.get("label") or "").strip()
    if lab:
        return lab
    return str(page.get("id") or "").upper()


def render_folio(page: dict, dt: date, week: str) -> str:
    pid = str(page.get("id") or "").upper()
    date_s = f"{dt.year} 年 {dt.month} 月 {dt.day} 日　星期{week}"
    return (
        f'<header class="folio">'
        f"<span>{html.escape(date_s)}</span>"
        f"<span>{html.escape(_page_label(page))}</span>"
        f"<span>{html.escape(pid)}</span>"
        f"</header>"
    )


def render_foot(page: dict, dt: date) -> str:
    pid = str(page.get("id") or "").upper()
    return (
        f'<footer class="foot">'
        f"<span>星期时报 · {dt.year} 年 {dt.month} 月 {dt.day} 日</span>"
        f"<span>{html.escape(pid)}</span>"
        f"</footer>"
    )


def render_mast(dt: date, week: str) -> str:
    return (
        '<header class="mast">\n'
        '<div class="pre"><span>All the News That’s Fit to Print</span><span>星期时报</span></div>\n'
        "<hr />\n<div class=\"en\">The Monday Times</div>\n<h1>星期时报</h1>\n"
        '<hr class="dbl" />\n'
        f'<div class="date"><span>{dt.year} 年 {dt.month} 月 {dt.day} 日　星期{week}</span></div>\n'
        "<hr />\n</header>"
    )


def render_figure(fig: dict) -> str:
    cls = fig.get("class") or "wrap"
    if cls not in {"wrap", "poster", "wide"}:
        cls = "wrap"
    src = html.escape(_figure_src(fig))
    cap = html.escape(fig.get("cap") or "")
    alt = html.escape(fig.get("alt") or fig.get("cap") or "")
    return (
        f'<figure class="article-figure {cls}">\n'
        f'<img src="{src}" alt="{alt}" />\n'
        f"<figcaption>{cap}</figcaption>\n"
        "</figure>"
    )


def compose(root: Path, stamp: str, lineup: dict | None = None) -> dict:
    try:
        stories = edition.load_evidence(root, stamp)
    except (ValueError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
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
    try:
        lead_id = pages[0].get("lead") if pages and pages[0].get("id") == "a1" else ""
        if not lead_id or lead_id not in stories:
            return {"ok": False, "error": "头版缺少已选头条"}
        edition.check_headline(stories[lead_id])
        used = [aid for page in pages for aid in [page.get("lead"), *(page.get("articles") or []), *(page.get("shorts") or [])] if aid]
        if len(used) != len(set(used)):
            return {"ok": False, "error": "同一稿件不能重复上版"}
        for aid in used:
            if aid not in stories or aid not in by_id:
                return {"ok": False, "error": f"稿件未选或不存在: {aid}"}
            meta, body = parse_front((root / by_id[aid]["path"]).read_text(encoding="utf-8"))
            if meta.get("evidence_digest") != edition.story_digest(stories[aid]) or meta.get("kind") != stories[aid]["kind"] or not body.strip():
                return {"ok": False, "error": f"稿件证据已变更或正文为空: {aid}"}
    except (ValueError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    folder = root / "desk" / "稿件" / stamp
    bodies = {}
    metas = {}
    ok_figs: list[str] = []
    skip_figs: list[str] = []
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
    nav = "".join(f'<a href="#{p["id"]}">{html.escape(_page_label(p))}</a>' for p in pages)
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
        if str(page.get("id") or "") == "a1":
            inner.append(render_mast(dt, week))
        else:
            inner.append(render_folio(page, dt, week))
        lead_id = page.get("lead") or ""
        arts = list(page.get("articles") or [])
        shorts = list(page.get("shorts") or [])
        def figures_for(aid: str) -> list:
            attached = []
            for fig in lineup.get("figures") or []:
                target = fig.get("article") or fig.get("article_id")
                if target != aid or (fig.get("page") and fig.get("page") != page["id"]):
                    continue
                src = _figure_src(fig)
                # Images must be local project assets and have meaningful descriptions.
                candidate = (root / src).resolve()
                try:
                    candidate.relative_to((root / "img").resolve())
                except ValueError:
                    skip_figs.append(fig.get("id") or src)
                    continue
                if not src or not candidate.is_file() or not (fig.get("alt") or fig.get("cap")):
                    skip_figs.append(fig.get("id") or src or page["id"])
                    continue
                attached.append(fig)
                ok_figs.append(fig.get("id") or src)
            return attached
        html_arts = [render_article(metas[aid], bodies[aid], stories[aid], lead=(aid == lead_id),
                                    figures=figures_for(aid))
                     for aid in [lead_id, *arts] if aid]
        inner.append(f"<div{flow_cls}>\n" + "\n\n".join(html_arts) + "\n</div>")
        if shorts:
            html_short = [render_article(metas[aid], bodies[aid], stories[aid],
                                         figures=figures_for(aid)) for aid in shorts]
            if html_short:
                band_n = min(3, len(html_short))
                inner.append(f'<div class="flow band n{band_n}">\n' + "\n\n".join(html_short) + "\n</div>")
        inner.append(render_foot(page, dt))
        chunks.append(f'<section class="page" id="{page["id"]}">\n' + "\n".join(inner) + "\n</section>")
    chunks.append("</body></html>")
    out_html = root / f"{stamp}.html"
    out_html.write_text("\n".join(chunks) + "\n", encoding="utf-8")
    (folder / "目录.json").write_text(json.dumps(packed, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "html": str(out_html.name),
        "pages": [
            {
                "id": p["id"],
                "n": len(([p.get("lead")] if p.get("lead") else []) + (p.get("articles") or [])),
                "n_shorts": len(p.get("shorts") or []),
            }
            for p in pages
        ],
        "n_copy": packed["n"],
        "total_chars": packed["total_chars"],
        "figures": ok_figs,
        "figures_skip": skip_figs,
        "catalog": str((folder / "目录.json").relative_to(root)).replace("\\", "/"),
    }
