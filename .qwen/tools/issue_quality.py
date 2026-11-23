from __future__ import annotations

from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

import catalog

PAGE_LINES = {"b": "人工智能", "c": "科技", "d": "娱乐", "e": "评论", "f": "动漫"}


class _IssueReader(HTMLParser):
    """Read the article text and figures actually present in the composed pages."""

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
    EXCLUDED = {"header", "footer", "nav", "figure", "figcaption", "table", "script", "style", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.pages = []
        self.navigation = []
        self.errors = []
        self.page = None
        self.story = None
        self.figure = None
        self.paragraph = None
        self.caption = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set((attrs.get("class") or "").split())
        parent_hidden = self.stack[-1][2] if self.stack else False
        style = re.sub(r"\s+", "", (attrs.get("style") or "").lower())
        hidden = parent_hidden or "hidden" in attrs or attrs.get("aria-hidden") == "true" or "display:none" in style or "visibility:hidden" in style or tag in {"script", "style", "template"}
        if tag == "a" and not hidden and any(t == "nav" and "nav" in c for t, c, _ in self.stack):
            self.navigation.append(attrs.get("href") or "")
        if tag == "section" and "page" in classes and not hidden:
            if self.page is not None:
                self.errors.append("版面嵌套")
            self.page = {"id": (attrs.get("id") or "").lower(), "stories": [], "figures": [], "flows": [], "header_before_body": False, "body_started": False}
            self.pages.append(self.page)
        if self.page is not None and not hidden:
            if tag == "header" and self.story is None and classes & {"mast", "folio"} and not self.page["body_started"]:
                self.page["header_before_body"] = True
            if "flow" in classes:
                self.page["flows"].append(sorted(classes))
            sid = attrs.get("data-story-id")
            if sid:
                if self.story is not None:
                    self.errors.append(f"稿件嵌套：{sid}")
                self.story = {"id": sid, "paragraphs": [], "started": False, "flow": next((entry[1] for entry in reversed(self.stack) if "flow" in entry[1]), set())}
                self.page["stories"].append(self.story)
            if self.story is not None:
                if tag == "figure":
                    self.figure = {"images": [], "caption": "", "wide": "wide" in classes,
                                   "id": attrs.get("data-figure-id") or "", "kind": attrs.get("data-image-kind") or "",
                                   "origin": attrs.get("data-image-origin") or "", "source": attrs.get("data-image-source") or "", "links": []}
                    self.page["figures"].append(self.figure)
                if tag == "img":
                    if self.figure is None:
                        self.errors.append(f"稿件 {self.story['id']} 的图片缺少图注容器")
                        self.page["figures"].append({"images": [{"alt": attrs.get("alt") or "", "src": attrs.get("src") or ""}], "caption": "", "wide": "wide" in classes, "id": "", "kind": "", "origin": "", "source": "", "links": []})
                    else:
                        self.figure["images"].append({"alt": attrs.get("alt") or "", "src": attrs.get("src") or ""})
                if tag == "figcaption" and self.figure is not None:
                    self.caption = []
                if tag == "a" and self.caption is not None and self.figure is not None:
                    self.figure["links"].append(attrs.get("href") or "")
                excluded = any(entry[0] in self.EXCLUDED for entry in self.stack) or tag in self.EXCLUDED
                if tag == "p" and not excluded and "article-sources" not in classes:
                    if "lede" in classes:
                        self.story["started"] = True
                        self.page["body_started"] = True
                    if self.story["started"]:
                        self.paragraph = []
        if tag not in self.VOID:
            self.stack.append((tag, classes, hidden))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_data(self, data):
        if self.stack and self.stack[-1][2]:
            return
        if self.paragraph is not None:
            self.paragraph.append(data)
        if self.caption is not None:
            self.caption.append(data)

    def handle_endtag(self, tag):
        if tag == "p" and self.paragraph is not None and self.story is not None:
            self.story["paragraphs"].append("".join(self.paragraph))
            self.paragraph = None
        if tag == "figcaption" and self.caption is not None and self.figure is not None:
            self.figure["caption"] = "".join(self.caption).strip()
            self.caption = None
        if tag == "figure":
            self.figure = None
        if tag == "article":
            self.story = None
        if tag == "section" and self.page is not None:
            self.page = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


def check_issue(document: str, stories: dict) -> dict:
    reader = _IssueReader()
    reader.feed(document)
    reader.close()
    errors = reader.errors
    pages = reader.pages
    if not 8 <= len(pages) <= 10:
        errors.append(f"全刊须为 8–10 版，实际 {len(pages)} 版")
    ids = [page["id"].lower() for page in pages]
    if reader.navigation != [f"#{pid}" for pid in ids]:
        errors.append("导航须按实际印版顺序逐版链接")
    letters = []
    expected = {}
    for pid in ids:
        match = re.fullmatch(r"([a-f])([1-9][0-9]*)", pid)
        if not match:
            errors.append(f"版号无效：{pid or '空'}")
            continue
        letter, num = match.group(1), int(match.group(2))
        expected[letter] = expected.get(letter, 0) + 1
        if num != expected[letter]:
            errors.append(f"版号不连续：{pid}")
        if not letters or letters[-1] != letter:
            letters.append(letter)
    if not letters or letters not in (["a", "b", "c", "d", "f"], ["a", "b", "c", "d", "e", "f"]) or ids.count("a1") != 1 or any(pid.startswith("a") and pid != "a1" for pid in ids):
        errors.append("版序须为 A1、B、C、D、可选 E、F")
    seen = set()
    total = 0
    figures = 0
    figure_ids = set()
    units = 0
    heavy = []
    last_page_by_line = {}
    for index, page in enumerate(pages):
        for item in page["stories"]:
            meta = stories.get(item["id"], {})
            if meta.get("line"):
                last_page_by_line[meta["line"]] = index
    for index, page in enumerate(pages):
        pid = page["id"]
        if not page["header_before_body"]:
            errors.append(f"{pid} 缺少正文之前的版头")
        page_chars = 0
        briefs = set()
        for item in page["stories"]:
            sid = item["id"]
            if sid in seen:
                errors.append(f"稿件重复上版：{sid}")
            seen.add(sid)
            meta = stories.get(sid)
            if not isinstance(meta, dict):
                errors.append(f"稿件缺少出稿证据：{sid}")
                meta = {}
            kind, line = meta.get("kind"), meta.get("line")
            if not kind or not line:
                errors.append(f"稿件缺少类型或采访线：{sid}")
            if pid[:1] in PAGE_LINES and line != PAGE_LINES[pid[0]]:
                errors.append(f"{pid} 的稿件 {sid} 与栏目不符")
            body = "\n".join(item["paragraphs"])
            chars = catalog.count_chars(body)
            han = len(re.findall(r"[\u4e00-\u9fff]", body))
            item.update(kind=kind, line=line, body_chars=chars, han=han)
            del item["paragraphs"], item["started"]
            item["flow"] = sorted(item["flow"])
            page_chars += chars
            if kind == "快讯":
                briefs.add(line or sid)
                if line and last_page_by_line.get(line) != index:
                    errors.append(f"{pid} 快讯 {sid} 不在线末页")
            else:
                units += 1
            if kind == "普通" and chars < 350:
                errors.append(f"{pid} 普通稿 {sid} 正文不足 350 字：{chars}")
            if (kind in {"深挖", "分析"} and han >= 2500 and len(page["stories"]) == 1
                and "n2" in item["flow"] and not any(fig["wide"] for fig in page["figures"])):
                heavy.append({"page": pid, "id": sid, "han": han})
        units += len(briefs)
        page["body_chars"] = page_chars
        total += page_chars
        wide = sum(fig["wide"] for fig in page["figures"])
        if index == 0:
            items = page["stories"]
            maximum = 1600 if wide else 2000
            if page_chars > maximum:
                errors.append(f"A1 正文上限为 {maximum} 字，实际 {page_chars}")
            if not items or items[0]["kind"] not in {"普通", "深挖"} or not 800 <= items[0]["body_chars"] <= 1200:
                errors.append("A1 主稿须为 800–1200 字的普通稿或短深挖")
            if len(items) > 2 or any(item["kind"] != "普通" or item["body_chars"] > 500 for item in items[1:]) or any(item["kind"] == "快讯" for item in items):
                errors.append("A1 最多另加一篇不超过 500 字的普通稿，不得有快讯")
            if not items or "n2" not in items[0]["flow"]:
                errors.append("A1 须使用 n2 版式")
        else:
            maximum = 2400 if wide else 2800
            if not 2200 <= page_chars <= maximum:
                errors.append(f"{pid} 正文须为 2200–{maximum} 字，实际 {page_chars}")
        if wide > 1 or (wide and len(page["stories"]) != 1):
            errors.append(f"{pid} 仅独占版位的主稿可配一张通栏图")
        for fig in page["figures"]:
            fid, kind, source = fig["id"].strip(), fig["kind"], fig["source"].strip()
            valid = True
            if not fid or fid in figure_ids:
                errors.append(f"{pid} 图片 ID 缺失或重复：{fid}")
                valid = False
            figure_ids.add(fid)
            if len(fig["images"]) != 1 or any(not img["alt"].strip() or not img["src"].strip() for img in fig["images"]) or not fig["caption"]:
                errors.append(f"{pid} 配图须有一张非空图片、alt 和图注")
                valid = False
            if kind in {"official-photo", "official-art"}:
                try:
                    url = urlsplit(source)
                    https_source = url.scheme == "https" and bool(url.hostname and url.path.strip("/")) and not url.username
                except ValueError:
                    https_source = False
                if not https_source or source not in fig["links"] or not fig["origin"].strip() or "公开资料" not in fig["caption"]:
                    errors.append(f"{pid} 官方配图须注明发布方及使用依据、提供 HTTPS 原件链接与公开资料标识")
                    valid = False
            elif kind in {"generated-illustration", "generated-portrait"}:
                if not fig["origin"].strip() or "人工智能生成／本报制图" not in fig["caption"]:
                    errors.append(f"{pid} 生成配图须记录替代原因并标明人工智能生成／本报制图")
                    valid = False
            else:
                errors.append(f"{pid} 图片类型无效或为不计配图的图表：{kind}")
                valid = False
            if valid:
                figures += 1
        del page["body_started"]
    if units > 20:
        errors.append(f"全刊稿件超过 20 份：{units}")
    if total < 18000:
        errors.append(f"全刊正文不足 18000 字：{total}")
    if not heavy:
        errors.append("缺少正文至少 2500 个汉字、独占 n2 且无 wide 图的长稿")
    if not 2 <= figures <= 5:
        errors.append(f"全刊须有 2–5 张文章配图，实际 {figures} 张")
    return {"ok": not errors, "errors": errors, "pages": pages, "figures": figures, "body_chars": total, "heavy": heavy}
