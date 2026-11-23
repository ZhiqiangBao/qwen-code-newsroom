"""Shared catalog: feeds.json, dead hosts, RSS, dates, classify."""
from __future__ import annotations

import json
import hashlib
import os
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlsplit, urlunsplit

from net import decode, get, last_request

ROOT = Path(__file__).resolve().parents[2]
LINES = ("人工智能", "科技", "娱乐", "动漫")
LINES_ALL = ("数据",) + LINES
LINE_LETTER = {"数据": "a", "人工智能": "b", "科技": "c", "娱乐": "d", "动漫": "f"}
STEM_RE = re.compile(r"^(深挖|普通)-\d{2}$|^快讯$|^补-\d+$")
FLASH_RE = re.compile(r"(?m)^##\s*快讯")
KIND_CHARS = {"快讯": 220, "普通": 550, "深挖": 1400, "评论": 900, "数据": 400}


def count_chars(text: str) -> int:
    text = re.sub(r"^---[\s\S]*?---\s*", "", text or "")
    han = len(re.findall(r"[\u4e00-\u9fff]", text))
    words = len(re.findall(r"[A-Za-z]+", text))
    nums = len(re.findall(r"\d+(?:\.\d+)?", text))
    return han + words + nums


def suggest_chars(kind: str, n_flash: int = 0) -> int:
    if kind == "快讯":
        n = max(1, int(n_flash or 0) or 1)
        return min(400, max(KIND_CHARS["快讯"], n * 70))
    return KIND_CHARS.get(kind, KIND_CHARS["普通"])


def load(root: Path | None = None) -> dict:
    base = root or ROOT
    return json.loads((base / "desk" / "feeds.json").read_text(encoding="utf-8"))


def window(stamp: str) -> tuple[str, str]:
    end = date.fromisoformat(stamp)
    start = end - timedelta(days=7)
    return start.isoformat(), end.isoformat()


def next_stem(folder: Path, kind: str) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    if kind == "快讯":
        return "快讯"
    if kind == "补":
        n = 0
        for path in folder.glob("补-*.md"):
            hit = re.match(r"^补-(\d+)$", path.stem)
            if hit:
                n = max(n, int(hit.group(1)))
        return f"补-{n + 1}"
    n = 0
    for path in folder.glob(f"{kind}-*.md"):
        hit = re.match(rf"^{re.escape(kind)}-(\d+)$", path.stem)
        if hit:
            n = max(n, int(hit.group(1)))
    return f"{kind}-{n + 1:02d}"


def slot_stem(source: str) -> str:
    return Path(str(source).replace("\\", "/")).stem


def check_slot(stamp: str, sid: str, line: str, source: str) -> str | None:
    source = str(source or "").replace("\\", "/").strip()
    sid = str(sid or "").strip()
    line = str(line or "").strip()
    if line not in LINES_ALL:
        return f"线名必须是 {'／'.join(LINES_ALL)}，收到 {line or '空'}"
    prefix = f"desk/素材/{stamp}/{line}/"
    if not source.startswith(prefix) or not source.endswith(".md") or source.count("/") < 3:
        return f"source 必须是 {prefix}<文件>.md，收到 {source or '空'}"
    stem = slot_stem(source)
    if stem == "行情":
        return "行情.md 不上槽，用 数据/普通-01.md"
    if not STEM_RE.match(stem):
        return f"素材文件名必须是 深挖-01／普通-01／快讯／补-1，收到 {stem}"
    expect = f"{line}-{stem}"
    if sid != expect:
        return f"槽 id 必须是 {expect}，收到 {sid}"
    return None


def flash_n(text: str) -> int:
    return len(FLASH_RE.findall(text or ""))


def in_window(day: str | None, start: str, end: str) -> bool:
    if not day:
        return False
    return start <= day[:10] < end


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def is_dead(url: str, cfg: dict) -> bool:
    host = host_of(url)
    for d in cfg.get("dead") or []:
        if host == d or host.endswith("." + d) or d in url:
            return True
    return False


def fetchable(url: str, cfg: dict) -> bool:
    if not url.startswith("http"):
        return False
    if is_dead(url, cfg):
        return False
    if "lapin.ithome.com" in url:
        return False
    if "douban.com/group/topic/" in url:
        return False
    return True


def classify(title: str, cfg: dict) -> str | None:
    for line, words in (cfg.get("keywords") or {}).items():
        if any(w.lower() in title.lower() for w in words):
            return line
    return None


def labs_hit(title: str, cfg: dict) -> list[str]:
    hit = []
    low = title.lower()
    for lab in cfg.get("labs") or []:
        names = lab.get("names") or []
        if any(n.lower() in low for n in names):
            hit.append(lab["id"])
    return hit


def parse_day(text: str | None) -> str | None:
    if not text:
        return None
    m = re.search(r"(20\d{2}-\d{2}-\d{2})", text)
    if m:
        return m.group(1)
    try:
        return parsedate_to_datetime(text.strip()).date().isoformat()
    except Exception:
        return None


def _xml_text(el) -> str:
    return (el.text or "").strip()


def rss_items(url: str, source: str, default_line: str, cfg: dict, limit: int = 20) -> list[dict]:
    if is_dead(url, cfg):
        return []
    code, raw, ctype = get(url, timeout=8)
    if code != 200 or not raw:
        return []
    text = decode(raw, ctype)
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    out = []
    for el in root.iter():
        tag = el.tag.split("}")[-1].lower()
        if tag not in {"item", "entry"}:
            continue
        title, link, when = "", "", None
        for c in el:
            ct = c.tag.split("}")[-1].lower()
            if ct == "title":
                title = _xml_text(c) or title
            elif ct in {"link", "id"}:
                href = _xml_text(c) or c.attrib.get("href") or ""
                if href:
                    link = href.strip()
            elif ct in {"pubdate", "published", "updated", "date"}:
                when = parse_day(_xml_text(c) or c.attrib.get("datetime"))
        if not title:
            continue
        item = {
            "source": source,
            "rank": len(out) + 1,
            "title": title,
            "url": link,
            "date": when,
            "line": classify(title, cfg) or default_line,
            "labs": labs_hit(title, cfg),
            "fetchable": fetchable(link, cfg),
            "role": "article" if fetchable(link, cfg) else "clue",
        }
        out.append(item)
        if len(out) >= limit:
            break
    return out


def weibo(cfg: dict, limit: int = 40) -> list[dict]:
    url = "https://weibo.com/ajax/side/hotSearch"
    code, raw, ctype = get(url, timeout=8, referer="https://weibo.com/")
    if code != 200:
        return []
    try:
        data = json.loads(decode(raw, ctype))
    except json.JSONDecodeError:
        return []
    items = []
    realtime = ((data.get("data") or {}).get("realtime") or [])[:limit]
    for i, it in enumerate(realtime, 1):
        word = it.get("word") or it.get("note") or ""
        if not word:
            continue
        items.append(
            {
                "source": "微博热搜",
                "rank": i,
                "title": word,
                "heat": it.get("num"),
                "label": it.get("label_name") or "",
                "line": classify(word, cfg),
                "url": "https://s.weibo.com/weibo?q=" + quote(word),
                "fetchable": False,
                "role": "clue",
                "labs": labs_hit(word, cfg),
            }
        )
    return items


def baidu(cfg: dict, tab: str, name: str, default_line: str | None, limit: int = 20) -> list[dict]:
    url = f"https://top.baidu.com/api/board?tab={tab}"
    code, raw, ctype = get(url, timeout=8, referer=f"https://top.baidu.com/board?tab={tab}")
    if code != 200:
        return []
    try:
        payload = json.loads(decode(raw, ctype))
    except json.JSONDecodeError:
        return []
    content = []
    for card in (payload.get("data") or {}).get("cards") or []:
        if card.get("content"):
            content = card["content"]
            break
    items = []
    for i, it in enumerate(content[:limit], 1):
        word = it.get("word") or it.get("query") or ""
        if not word:
            continue
        href = it.get("url") or it.get("appUrl") or ""
        items.append(
            {
                "source": name,
                "rank": i,
                "title": word,
                "heat": it.get("hotScore"),
                "line": classify(word, cfg) or default_line,
                "url": href,
                "fetchable": fetchable(href, cfg) if href else False,
                "role": "article" if fetchable(href, cfg) and href else "clue",
                "labs": labs_hit(word, cfg),
            }
        )
    return items


def ithome(cfg: dict, limit: int = 25) -> list[dict]:
    url = "https://api.ithome.com/json/newslist/news"
    if is_dead(url, cfg):
        return []
    code, raw, ctype = get(url, timeout=8, referer="https://www.ithome.com/")
    if code != 200:
        return []
    try:
        payload = json.loads(decode(raw, ctype))
    except json.JSONDecodeError:
        return []
    items = []
    for it in payload.get("newslist") or []:
        title = it.get("title") or ""
        path = it.get("url") or ""
        href = path if str(path).startswith("http") else "https://www.ithome.com" + path
        if "lapin.ithome.com" in href:
            continue
        day = parse_day(it.get("postdate") or "")
        line = classify(title, cfg)
        if line not in {"人工智能", "科技"}:
            line = "科技"
        items.append(
            {
                "source": "IT之家最新",
                "rank": len(items) + 1,
                "title": title,
                "heat": it.get("hitcount"),
                "line": line,
                "url": href,
                "date": day,
                "labs": labs_hit(title, cfg),
                "fetchable": fetchable(href, cfg),
                "role": "article" if fetchable(href, cfg) else "clue",
            }
        )
        if len(items) >= limit:
            break
    return items


def bili(cfg: dict) -> list[dict]:
    url = "https://api.bilibili.com/pgc/web/rank/list?season_type=1&day=3"
    code, raw, ctype = get(url, timeout=8, referer="https://www.bilibili.com/")
    if code != 200:
        return []
    try:
        payload = json.loads(decode(raw, ctype))
    except json.JSONDecodeError:
        return []
    rows = ((payload.get("result") or {}).get("list")) or []
    items = []
    for i, it in enumerate(rows[:15], 1):
        title = it.get("title") or ""
        href = it.get("url") or it.get("link") or ""
        items.append(
            {
                "source": "B站番剧榜",
                "rank": i,
                "title": title,
                "line": "动漫",
                "url": href,
                "fetchable": fetchable(href, cfg) if href else False,
                "role": "clue",
                "labs": [],
            }
        )
    return items


def douban_group(cfg: dict, gid: str, name: str, region: str) -> list[dict]:
    url = f"https://www.douban.com/group/{gid}/discussion?start=0"
    if is_dead(url, cfg):
        return []
    code, raw, ctype = get(url, timeout=8, referer="https://www.douban.com/")
    if code != 200:
        return []
    html = decode(raw, ctype)
    items = []
    for m in re.finditer(
        r'href="(https://www\.douban\.com/group/topic/\d+/)\?[^"]*"\s+title="([^"]+)"',
        html,
    ):
        title = m.group(2).strip()
        items.append(
            {
                "source": f"豆瓣·{name}",
                "rank": len(items) + 1,
                "title": title,
                "line": "娱乐",
                "region": region,
                "url": m.group(1),
                "fetchable": False,
                "role": "clue",
                "labs": [],
            }
        )
        if len(items) >= 20:
            break
    return items


def sec_submissions(spec: dict, cfg: dict) -> list[dict]:
    """Use SEC's public submissions JSON only with the operator's identifying user agent."""
    agent = str(os.environ.get("SEC_USER_AGENT") or cfg.get("sec_user_agent") or "").strip()
    if not agent:
        raise ValueError("SEC user agent not configured")
    req = urllib.request.Request(spec["url"], headers={"User-Agent": agent, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("SEC response too large")
    payload = json.loads(raw)
    recent = ((payload.get("filings") or {}).get("recent") or {})
    company = payload.get("name") or spec.get("name") or "SEC filing"
    cik = str(int(payload["cik"]))
    out = []
    for accession, day, form, document in zip(recent.get("accessionNumber") or [],
                                               recent.get("filingDate") or [],
                                               recent.get("form") or [],
                                               recent.get("primaryDocument") or []):
        if not accession or not document or not parse_day(day):
            continue
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{document}"
        title = f"{company} SEC {form} · {day}"
        out.append({"source": spec.get("name") or "SEC EDGAR", "rank": len(out) + 1,
                    "title": title, "url": url, "date": day, "line": spec.get("line"),
                    "labs": labs_hit(title, cfg), "fetchable": True, "role": "article"})
        if len(out) >= 100:
            break
    return out


def quotes_tencent(cfg: dict) -> dict:
    url = (cfg.get("quotes") or {}).get("tencent") or ""
    if not url or is_dead(url, cfg):
        return {"ok": False, "rows": [], "error": "no url"}
    code, raw, ctype = get(url, timeout=8)
    if code != 200:
        return {"ok": False, "rows": [], "error": f"http {code}"}
    text = decode(raw, ctype or "text/plain; charset=gbk")
    rows = []
    for line in text.splitlines():
        if "~" not in line:
            continue
        body = line.split("=", 1)[-1].strip().strip(";").strip('"')
        parts = body.split("~")
        if len(parts) < 6:
            continue
        rows.append(
            {
                "name": parts[1],
                "code": parts[2],
                "price": parts[3],
                "change": parts[4],
                "pct": parts[5],
                "via": "tencent",
            }
        )
    return {"ok": bool(rows), "rows": rows, "source": url}


def quotes_baidu(cfg: dict) -> dict:
    url = (cfg.get("quotes") or {}).get("baidu") or ""
    if not url or is_dead(url, cfg):
        return {"ok": False, "rows": [], "error": "no url"}
    code, raw, ctype = get(url, timeout=8, referer="https://finance.baidu.com/")
    if code != 200 or not raw:
        return {"ok": False, "rows": [], "error": f"http {code}"}
    try:
        data = json.loads(decode(raw, ctype))
    except json.JSONDecodeError:
        return {"ok": False, "rows": [], "error": "bad json"}
    result = data.get("Result") or []
    tpl = {}
    if result and isinstance(result[0], dict):
        tpl = (result[0].get("TplData") or {}).get("result") or {}
    rows = []
    for block in tpl.get("hot_index") or []:
        region = block.get("name") or ""
        for it in block.get("index_list") or []:
            if not isinstance(it, dict):
                continue
            name = it.get("name") or ""
            last = it.get("last_px") or ""
            if not name or not last:
                continue
            pct = str(it.get("px_change_rate") or "").replace("%", "")
            rows.append(
                {
                    "name": name,
                    "code": it.get("code") or "",
                    "price": last,
                    "change": it.get("px_change") or "",
                    "pct": pct,
                    "region": region,
                    "via": "baidu",
                }
            )
    return {"ok": bool(rows), "rows": rows, "source": url}


def quotes(cfg: dict, previous: dict | None = None) -> dict:
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {"tencent": pool.submit(quotes_tencent, cfg), "baidu": pool.submit(quotes_baidu, cfg)}
        results = {}
        for name, future in futures.items():
            try:
                results[name] = future.result()
            except Exception as exc:
                results[name] = {"ok": False, "rows": [], "error": type(exc).__name__}
    previous = previous or {}
    for name, result in results.items():
        old = previous.get(name) or {}
        if not result.get("ok") and old.get("rows"):
            results[name] = {**old, "reused": True, "error": result.get("error") or "no data"}
    merged = merge_quotes(results)
    merged["by_source"] = results
    return merged


def merge_quotes(results: dict) -> dict:
    rows, seen, sources = [], set(), []
    for name in ("tencent", "baidu"):
        result = results.get(name) or {}
        if result.get("source"):
            sources.append(result["source"])
        for row in result.get("rows") or []:
            key = row.get("code") or row.get("name")
            if key and key in seen:
                continue
            rows.append(row)
            if key:
                seen.add(key)
    out = {"ok": bool(rows), "rows": rows, "source": sources[0] if sources else "", "sources": sources}
    for name in ("tencent", "baidu"):
        result = results.get(name) or {}
        out[name] = {"ok": bool(result.get("ok")), "n": len(result.get("rows") or []),
                     "error": result.get("error"), "reused": bool(result.get("reused"))}
    return out


def canonical_url(url: str) -> str:
    try:
        p = urlsplit(url.strip())
        if p.scheme.lower() not in {"http", "https"} or not p.netloc:
            return ""
        query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                 if not (k.lower().startswith("utm_") or k.lower() in {"from", "source", "spm", "ref"})]
        return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), urlencode(sorted(query)), ""))
    except (ValueError, AttributeError):
        return ""


def normalized_title(title: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", (title or "").casefold())


def dedupe(rows: list[dict]) -> list[dict]:
    # Group events but retain each independently attributable source for editorial review.
    out, urls, titles = [], {}, {}
    for original in rows:
        row = dict(original)
        url = canonical_url(row.get("url") or "")
        title = normalized_title(row.get("title") or "")
        match = urls.get(url) if url else None
        if match is None and title:
            match = titles.get(title)
        if match is None:
            match = len(out)
            row["evidence"] = []
            out.append(row)
        else:
            evidence = {k: row.get(k) for k in ("title", "url", "source", "date", "fetchable", "role")}
            for candidate in [evidence, *(row.get("evidence") or [])]:
                if candidate not in out[match]["evidence"]:
                    out[match]["evidence"].append(candidate)
            # A dated article is more useful than an undated social clue, but preserve both.
            if row.get("role") == "article" and out[match].get("role") != "article":
                previous = {k: out[match].get(k) for k in ("title", "url", "source", "date", "fetchable", "role")}
                evidence_list = out[match]["evidence"]
                if previous not in evidence_list:
                    evidence_list.append(previous)
                out[match] = {**row, "evidence": evidence_list}
        if url:
            urls[url] = match
        if title:
            titles[title] = match
    return out


def _source_tasks(cfg: dict, lines: tuple[str, ...], include_hot: bool) -> list[tuple]:
    tasks = []
    if include_hot:
        for spec in cfg.get("hot") or []:
            kind = spec.get("kind")
            if kind == "weibo":
                tasks.append(("hot:" + spec["id"], "hot", "", lambda: weibo(cfg)))
            elif kind == "baidu":
                tasks.append(("hot:" + spec["id"], "hot", "", lambda spec=spec: baidu(cfg, spec["tab"], spec["name"], spec.get("line"))))
        for group in cfg.get("groups") or []:
            tasks.append(("group:" + group["id"], "hot", "", lambda group=group: douban_group(cfg, group["id"], group["name"], group.get("region") or "")))
    for spec in cfg.get("feeds") or []:
        line, kind = spec.get("line"), spec.get("kind") or "rss"
        if line not in lines:
            continue
        if kind == "rss":
            fn = lambda spec=spec, line=line: rss_items(spec["url"], spec["name"], line, cfg)
        elif kind == "json" and "ithome.com" in spec.get("url", ""):
            fn = lambda: ithome(cfg)
        elif kind == "bili":
            fn = lambda: bili(cfg)
        elif kind == "sec":
            fn = lambda spec=spec: sec_submissions(spec, cfg)
        else:
            continue
        tasks.append(("feed:" + spec["id"], "feed", line, fn))
    return tasks


def collect_sources(cfg: dict, cache_dir: Path, start: str, end: str,
                    lines: tuple[str, ...] = LINES, include_hot: bool = True) -> tuple[list, dict, list]:
    """Bounded source collection; successful nonempty responses are reusable for a short TTL."""
    ttl = max(0, min(int(cfg.get("cache_ttl_seconds", 900)), 86400))
    workers = max(1, min(int(cfg.get("max_workers", 6)), 12))
    cache_dir.mkdir(parents=True, exist_ok=True)
    tasks = _source_tasks(cfg, lines, include_hot)
    signature = hashlib.sha256(json.dumps(cfg, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    def run(task):
        key, category, line, fn = task
        path = cache_dir / (hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json")
        old = {}
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        now = time.time()
        if old.get("key") != key or old.get("signature") != signature:
            old = {}
        prior = [item for item in old.get("items") or []
                 if isinstance(item, dict) and in_window(item.get("date"), start, end)]
        if old.get("items") and 0 <= now - old.get("time", 0) < ttl:
            return task, old["items"], {"id": key, "status": "cached", "n": len(old["items"])}
        try:
            if key.startswith("feed:sec-") and not str(os.environ.get("SEC_USER_AGENT") or cfg.get("sec_user_agent") or "").strip():
                return task, [], {"id": key, "status": "not_configured", "n": 0,
                                  "error": "SEC user agent required"}
            items = fn()
            request = {} if key.startswith("feed:sec-") else last_request()
            status = "ok" if items else (request.get("status") if request.get("status") not in (None, "ok") else "empty_or_parse_error")
        except Exception as exc:
            items, request, status = [], {}, "error"
            request["error"] = type(exc).__name__
        # Retain dated in-window coverage after a refresh or a temporary source failure.
        # Undated old clues and dates outside this edition do not survive refresh.
        fresh = [item for item in items if not item.get("date") or in_window(item.get("date"), start, end)]
        if items:
            items = dedupe(fresh + prior)[:100]
        elif prior:
            items = prior[:100]
            status = "degraded"
        diag = {"id": key, "status": status, "n": len(items),
                "retained": len(prior), **{k: v for k, v in request.items() if k != "status"}}
        if items:
            record = {"key": key, "signature": signature,
                      "time": now if status == "ok" else old.get("time", 0), "items": items}
            fd, tmp = tempfile.mkstemp(dir=cache_dir, prefix=".source-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(record, stream, ensure_ascii=False)
                os.replace(tmp, path)
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)
        elif old:
            path.unlink(missing_ok=True)
        return task, items, diag
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(run, tasks))
    hot, feeds, diagnostics = [], {line: [] for line in lines}, []
    for task, items, diag in results:
        _, category, line, _ = task
        diag.update({"category": category, "line": line})
        diagnostics.append(diag)
        for original in items:
            item = dict(original)
            day = item.get("date")
            if day and not in_window(day, start, end):
                continue
            if not day:
                item["role"] = "clue"
                item["fetchable"] = False
                item["date_status"] = "unknown"
            if category == "hot":
                hot.append(item)
            else:
                feeds[line].append(item)
    return dedupe(hot), {line: dedupe(rows) for line, rows in feeds.items()}, diagnostics


def collect_hot(cfg: dict) -> list[dict]:
    # Legacy entry point, retained for callers outside the edition workflow.
    rows = weibo(cfg)
    for tab, name, line in (("realtime", "百度热搜", None), ("finance", "百度财经", "科技"), ("movie", "百度电影", "娱乐"), ("teleplay", "百度电视剧", "娱乐")):
        rows += baidu(cfg, tab, name, line)
    rows += ithome(cfg) + bili(cfg)
    for g in cfg.get("groups") or []:
        rows += douban_group(cfg, g["id"], g["name"], g.get("region") or "")
    return rows


def collect_feed(cfg: dict, line: str, start: str, end: str) -> list[dict]:
    rows = []
    for _, _, _, fn in _source_tasks(cfg, (line,), False):
        rows += fn()
    return [it for it in rows if not it.get("date") or in_window(it["date"], start, end)]


def headline_pool(rows: list[dict]) -> list[dict]:
    pool = []
    for it in rows:
        src = it.get("source") or ""
        rank = it.get("rank") or 99
        if src == "微博热搜" and rank <= 15 and it.get("line"):
            pool.append(it)
        elif src == "百度热搜" and rank <= 10 and it.get("line"):
            pool.append(it)
        elif src.startswith("IT之家") and rank <= 8:
            pool.append(it)
        elif src.startswith("量子位") and rank <= 8:
            pool.append(it)
        elif it.get("labs") and it.get("fetchable"):
            pool.append(it)
    return pool[:40]


def lab_status(items: list[dict], cfg: dict, start: str, end: str) -> dict:
    found: dict[str, list] = {lab["id"]: [] for lab in cfg.get("labs") or []}
    for it in items:
        day = it.get("date")
        if day and not in_window(day, start, end):
            continue
        for lab_id in it.get("labs") or []:
            if lab_id in found and len(found[lab_id]) < 5:
                found[lab_id].append(
                    {
                        "title": it.get("title"),
                        "url": it.get("url"),
                        "date": day,
                        "source": it.get("source"),
                        "fetchable": it.get("fetchable"),
                    }
                )
    missing = [k for k, v in found.items() if not v]
    return {"hit": {k: v for k, v in found.items() if v}, "missing": missing}


def fetch_urls(by_line: dict, limit_each: int = 8) -> list[dict]:
    out = []
    seen = set()
    for line, rows in by_line.items():
        n = 0
        ranked = sorted(rows, key=lambda x: (0 if x.get("labs") else 1, x.get("rank") or 99))
        for it in ranked:
            url = it.get("url") or ""
            if not it.get("fetchable") or not it.get("date") or canonical_url(url) in seen:
                continue
            seen.add(canonical_url(url))
            out.append(
                {
                    "line": line,
                    "title": it.get("title"),
                    "url": url,
                    "date": it.get("date"),
                    "source": it.get("source"),
                    "labs": it.get("labs") or [],
                    "evidence": it.get("evidence") or [],
                }
            )
            n += 1
            if n >= limit_each:
                break
    return out


def probe(url: str, cfg: dict) -> list[dict]:
    parsed = urlparse(url if "://" in url else "https://" + url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if is_dead(origin + "/", cfg):
        return [{"url": origin, "skipped": "dead"}]
    rows = []
    for path in cfg.get("probe_paths") or []:
        target = origin.rstrip("/") + path
        code, raw, ctype = get(target, timeout=6)
        text = decode(raw, ctype)[:400]
        kind = "empty"
        if raw.lstrip()[:1] in b"{[":
            kind = "json"
        elif "<rss" in text.lower() or "<feed" in text.lower():
            kind = "rss"
        elif code == 200 and len(raw) > 400:
            kind = "html"
        rows.append({"url": target, "code": code, "bytes": len(raw), "kind": kind})
        if kind == "rss":
            break
    return rows


def check_feeds(cfg: dict) -> list[dict]:
    rows = []
    seen = set()
    for spec in cfg.get("feeds") or []:
        url = spec.get("url") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        if is_dead(url, cfg):
            rows.append({"id": spec["id"], "url": url, "skipped": "dead"})
            continue
        code, raw, ctype = get(url, timeout=8)
        kind = "empty"
        text = decode(raw, ctype)[:300]
        if raw.lstrip()[:1] in b"{[":
            kind = "json"
        elif "<rss" in text.lower() or "<feed" in text.lower() or "<item" in text.lower():
            kind = "rss"
        elif code == 200:
            kind = "html"
        rows.append(
            {
                "id": spec["id"],
                "line": spec.get("line"),
                "code": code,
                "bytes": len(raw),
                "kind": kind,
                "ok": code == 200 and kind in {"rss", "json"} and len(raw) > 200,
            }
        )
    return rows
