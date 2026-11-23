"""Evidence and reader-facing checks shared by writing, composition and release."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit


KINDS = {"普通", "快讯", "深挖", "分析", "评论"}
LINES = {"人工智能", "科技", "娱乐", "动漫", "数据", "评论"}
ID = re.compile(r"[A-Za-z0-9\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff_-]{0,79}\Z")
INTERNAL = re.compile(
    r"(?:desk|rules)[/\\]|mcp__desk__|写稿\s*llama\.cpp|拼版\s*主编|"
    r"(?:本|该)(?:取材|写稿|编辑)?工位|子代理|未获取清单|未获取|"
    r"正文(?:未|没有)抓取|本次抓取|抓取失败|素材未提供|原文未抓取|"
    r"本期无法提供|取材(?:说明|过程)|待补(?:素材|清单)|"
    r"记者未直接打开|待进一步人工确认|尚待核实原始声明",
    re.IGNORECASE,
)


def issue_date(stamp: str) -> date:
    if not isinstance(stamp, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", stamp):
        raise ValueError("刊头日期须为 YYYY-MM-DD")
    return date.fromisoformat(stamp)


def _required(record: dict, key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"缺少 {key}")
    return value.strip()


def _records(record: dict, key: str) -> list[dict]:
    value = record.get(key)
    if not isinstance(value, list) or not value or any(not isinstance(row, dict) for row in value):
        raise ValueError(f"{key} 须为非空记录数组")
    return value


def _check_sources(story: dict, end: date) -> dict[str, dict]:
    sources = {}
    urls = set()
    for source in _records(story, "sources"):
        sid = _required(source, "id")
        url = _required(source, "url")
        parsed = urlsplit(url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
                or any(ch.isspace() for ch in url) or not parsed.path.strip("/")):
            raise ValueError(f"{sid} 须指向可定位的外部原件或文章")
        canonical = (parsed.hostname.lower().removeprefix("www."), parsed.path.rstrip("/"), parsed.query)
        if not ID.fullmatch(sid) or sid in sources or canonical in urls:
            raise ValueError(f"来源 ID 或链接重复或无效：{sid}")
        _required(source, "name")
        _required(source, "origin")
        if source.get("kind") not in {"primary", "independent", "secondary"}:
            raise ValueError(f"{sid} 缺少有效的来源类型")
        if issue_date(_required(source, "published_at")) >= end:
            raise ValueError(f"{sid} 发布于刊头日期之后或当天")
        sources[sid] = source
        urls.add(canonical)
    return sources


def _check_story(story: dict, start: date, end: date) -> str:
    sid = _required(story, "id")
    if not ID.fullmatch(sid) or story.get("kind") not in KINDS or story.get("line") not in LINES:
        raise ValueError(f"稿件 ID、采访线或体裁无效：{sid}")
    _required(story, "title")
    event = issue_date(_required(story, "event_date"))
    if not start <= event < end:
        raise ValueError(f"事件日期不在本期取材窗口：{sid}")
    if story.get("risk") not in {"normal", "high"}:
        raise ValueError(f"须标注稿件风险：{sid}")
    sources = _check_sources(story, end)
    facts = _records(story, "facts")
    used = set()
    for fact in facts:
        _required(fact, "text")
        for ref in _records(fact, "refs"):
            source_id = _required(ref, "source")
            if source_id not in sources:
                raise ValueError(f"事实引用了未知来源：{source_id}")
            _required(ref, "locator")
            _required(ref, "excerpt")
            used.add(source_id)
    if used != sources.keys():
        raise ValueError(f"存在未用于核对事实的来源：{sid}")
    if "table" in story:
        table = story["table"]
        if not isinstance(table, dict):
            raise ValueError(f"{sid} 的数据表须为对象")
        _required(table, "caption")
        columns = table.get("columns")
        if not isinstance(columns, list) or not 2 <= len(columns) <= 6 or any(
                not isinstance(value, str) or not value.strip() for value in columns):
            raise ValueError(f"{sid} 的数据表须有 2 至 6 列列名")
        for row in _records(table, "rows"):
            cells = row.get("cells")
            fact_index = row.get("fact")
            if (type(fact_index) is not int or not 1 <= fact_index <= len(facts)
                    or not isinstance(cells, list) or len(cells) != len(columns)
                    or any(not isinstance(value, str) or not value.strip() for value in cells)):
                raise ValueError(f"{sid} 的数据行须对应经核对的事实与完整列")
    if story["kind"] == "分析":
        for key in ("question", "baseline", "limit"):
            _required(story, key)
        if len(facts) < 2 or len(sources) < 2:
            raise ValueError(f"分析稿缺少可核对的比较材料：{sid}")
    if story["risk"] == "high":
        _required(story, "response")
        independent = {source["origin"].strip().casefold() for source in sources.values()
                       if source["kind"] in {"primary", "independent"}}
        if len(independent) < 2:
            raise ValueError(f"高风险稿缺少独立核实：{sid}")
    return sid


def _evidence_path(root: Path, stamp: str) -> Path:
    return root / "desk" / "证据" / f"{stamp}.json"


def _validate_evidence(stamp: str, document: dict) -> dict[str, dict]:
    end = issue_date(stamp)
    if not isinstance(document, dict) or document.get("date") != stamp:
        raise ValueError("证据表日期与刊头不符")
    stories = {}
    start = end - timedelta(days=7)
    for story in _records(document, "stories"):
        sid = _check_story(story, start, end)
        if sid in stories:
            raise ValueError(f"稿件 ID 重复：{sid}")
        stories[sid] = story
    if sum(story["kind"] == "分析" for story in stories.values()) != 1:
        raise ValueError("本期须选定一篇分析稿")
    return stories


def load_evidence(root: Path, stamp: str) -> dict[str, dict]:
    issue_date(stamp)
    path = _evidence_path(root, stamp)
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"无法读取本期证据表：{path.name}") from exc
    return _validate_evidence(stamp, document)


def save_evidence(root: Path, stamp: str, raw: str) -> dict:
    document = json.loads(raw)
    stories = _validate_evidence(stamp, document)
    path = _evidence_path(root, stamp)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        try:
            json.dump(document, output, ensure_ascii=False, indent=2)
            output.write("\n")
        except BaseException:
            output.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return {"ok": True, "path": path.relative_to(root).as_posix(), "ids": list(stories),
            "analysis": next(sid for sid, story in stories.items() if story["kind"] == "分析")}


def check_headline(story: dict) -> None:
    sources = story["sources"]
    origins = {source["origin"].strip().casefold() for source in sources
               if source["kind"] == "independent"}
    if not any(source["kind"] == "primary" for source in sources) and len(origins) < 2:
        raise ValueError("头条缺少一手证据或两条独立证据链")


def story_digest(story: dict) -> str:
    serialized = json.dumps(story, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def issue_digest(root: Path, stamp: str) -> str:
    return story_digest(load_evidence(root, stamp))


class ReaderPage(HTMLParser):
    """Read document text and source links scoped to each public story."""

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
    SKIP = {"script", "style", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, str | None, bool]] = []
        self.links: dict[str, set[str]] = {}
        self.text: list[str] = []
        self.errors: list[str] = []
        self.ids: set[str] = set()
        self.anchors: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        props = dict(attrs)
        sid = props.get("data-story-id")
        inherited = self.stack[-1] if self.stack else ("", None, False)
        hidden = inherited[2] or tag in self.SKIP
        if sid:
            if sid in self.links or inherited[1]:
                self.errors.append(f"重复或嵌套的稿件：{sid}")
            self.links.setdefault(sid, set())
        story = sid or inherited[1]
        target = props.get("href")
        if tag == "a" and target:
            if target.startswith("#") and len(target) > 1:
                self.anchors.add(target[1:])
            if story:
                self.links[story].add(target)
        el_id = props.get("id")
        if el_id:
            if el_id in self.ids:
                self.errors.append(f"重复的锚点：{el_id}")
            self.ids.add(el_id)
        if tag == "img" and not (props.get("alt") or "").strip():
            self.errors.append("上版图片缺少替代文字")
        if not hidden:
            self.text.extend(props.get(name) or "" for name in ("alt", "aria-label", "title"))
        if tag not in self.VOID:
            self.stack.append((tag, story, hidden))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data: str) -> None:
        if not self.stack or not self.stack[-1][2]:
            self.text.append(data)


def check_document(root: Path, stamp: str, document: str) -> None:
    stories = load_evidence(root, stamp)
    page = ReaderPage()
    page.feed(document)
    page.close()
    if page.errors:
        raise ValueError("；".join(page.errors))
    if page.anchors - page.ids:
        raise ValueError("导航指向不存在的版面或稿件")
    if page.links.keys() != stories.keys():
        raise ValueError("成报稿件与证据表的入选稿件不一致")
    for sid, story in stories.items():
        required_urls = {source["url"] for source in story["sources"]}
        if not required_urls <= page.links[sid]:
            raise ValueError(f"稿件缺少可点击出处：{sid}")
    internal = INTERNAL.search(" ".join(page.text))
    if internal:
        raise ValueError(f"成报包含内部编辑文字：{internal.group(0)}")
