"""Shared catalog: feeds.json, dead hosts, RSS, dates, classify."""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote, urlparse

from net import decode, get

ROOT = Path(__file__).resolve().parents[2]
LINES = ("人工智能", "科技", "娱乐", "动漫")


def load(root: Path | None = None) -> dict:
    base = root or ROOT
    return json.loads((base / "desk" / "feeds.json").read_text(encoding="utf-8"))


def window(stamp: str) -> tuple[str, str]:
    end = date.fromisoformat(stamp)
    start = end - timedelta(days=7)
    return start.isoformat(), end.isoformat()


def in_window(day: str | None, start: str, end: str) -> bool:
    if not day:
        return False
    return start <= day[:10] <= end


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
            }
        )
    return {"ok": bool(rows), "rows": rows, "source": url}


def collect_hot(cfg: dict) -> list[dict]:
    rows: list[dict] = []
    rows += weibo(cfg)
    rows += baidu(cfg, "realtime", "百度热搜", None)
    rows += baidu(cfg, "finance", "百度财经", "科技")
    rows += baidu(cfg, "movie", "百度电影", "娱乐")
    rows += baidu(cfg, "teleplay", "百度电视剧", "娱乐")
    rows += ithome(cfg)
    rows += bili(cfg)
    for g in cfg.get("groups") or []:
        rows += douban_group(cfg, g["id"], g["name"], g.get("region") or "")
    return rows


def collect_feed(cfg: dict, line: str, start: str, end: str) -> list[dict]:
    rows: list[dict] = []
    for spec in cfg.get("feeds") or []:
        if spec.get("line") != line:
            continue
        kind = spec.get("kind") or "rss"
        if kind == "rss":
            rows += rss_items(spec["url"], spec["name"], line, cfg)
        elif kind == "json" and "ithome.com" in spec.get("url", ""):
            rows += ithome(cfg)
        elif kind == "bili":
            rows += bili(cfg)
    fresh = []
    for it in rows:
        day = it.get("date")
        if day and not in_window(day, start, end):
            continue
        fresh.append(it)
    return fresh


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
            if not it.get("fetchable") or url in seen:
                continue
            seen.add(url)
            out.append(
                {
                    "line": line,
                    "title": it.get("title"),
                    "url": url,
                    "date": it.get("date"),
                    "source": it.get("source"),
                    "labs": it.get("labs") or [],
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
