"""Tiny HTTP GET. No third-party deps."""
from __future__ import annotations

import ssl
import urllib.error
import urllib.request

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def get(
    url: str,
    timeout: int = 8,
    referer: str | None = None,
    accept: str = "application/json, application/rss+xml, application/xml, text/html;q=0.8, */*;q=0.5",
) -> tuple[int, bytes, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": accept,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7",
            "Referer": referer or (url.rsplit("/", 1)[0] + "/"),
        },
        method="GET",
    )
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.status, resp.read(400_000), resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read(2000) if e.fp else b"", str(e.reason)
    except Exception:
        return 0, b"", ""


def decode(raw: bytes, ctype: str = "") -> str:
    low = (ctype or "").lower()
    if "gbk" in low or "gb2312" in low or "gb18030" in low:
        return raw.decode("gbk", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("gbk", errors="replace")
