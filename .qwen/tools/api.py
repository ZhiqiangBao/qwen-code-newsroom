"""OpenAI-compatible /v1 client. Copywriter talks only to this.

Endpoints are tried in writer.json order. The first with a `launch` block
is llama.cpp: discover, then start, then POST /v1/chat/completions.
Later endpoints are already-running APIs (ollama, cloud, another llama).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import llama

HERE = Path(__file__).resolve().parent


def load() -> dict:
    path = HERE / "writer.json"
    if not path.is_file():
        return {"timeout": 180, "temperature": 0.3, "max_tokens": 3500, "endpoints": []}
    return json.loads(path.read_text(encoding="utf-8"))


def endpoints() -> list[dict]:
    return [dict(ep) for ep in (load().get("endpoints") or []) if isinstance(ep, dict)]


def v1_url(url: str) -> str:
    return llama.v1_url(url)


def _headers(ep: dict) -> dict:
    headers = {"Content-Type": "application/json"}
    key = (os.environ.get(ep.get("api_key_env") or "") or ep.get("api_key") or "").strip()
    if key:
        headers["Authorization"] = "Bearer " + key
    return headers


def _get_json(url: str, headers: dict | None = None, timeout: float = 1.5) -> dict | None:
    try:
        req = urllib.request.Request(url, headers=headers or {}, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(8000)
        text = raw.decode("utf-8", "replace").lstrip()
        if not text or text.startswith("<"):
            return None
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def ping(ep: dict) -> dict:
    """True OpenAI /v1: GET /v1/models must be JSON, not HTML."""
    base = (ep.get("base_url") or "").strip()
    if not base:
        return {"ok": False, "error": "未写 base_url"}
    v1 = v1_url(base)
    models = _get_json(v1 + "/models", _headers(ep))
    if models and ("data" in models or models.get("object") == "list"):
        names = []
        for it in models.get("data") or []:
            if isinstance(it, dict) and it.get("id"):
                names.append(it["id"])
        return {"ok": True, "v1": v1, "models": names[:8]}
    return {"ok": False, "error": "不是 /v1 API（HTML 或无 models）", "v1": v1}


def _chat(ep: dict, messages: list[dict], cfg: dict) -> dict:
    v1 = v1_url(ep.get("base_url") or "")
    payload = {
        "model": ep.get("model") or "local",
        "messages": messages,
        "temperature": cfg.get("temperature", 0.3),
        "max_tokens": int(cfg.get("max_tokens") or 3500),
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        v1 + "/chat/completions",
        data=data,
        headers=_headers(ep),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=int(cfg.get("timeout") or 180)) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"http {e.code}", "detail": e.read()[:400].decode("utf-8", "replace"), "v1": v1}
    except Exception as e:
        return {"ok": False, "error": str(e), "v1": v1}
    try:
        msg = body["choices"][0]["message"]
        text = msg.get("content") or ""
        if not text and msg.get("reasoning_content"):
            text = msg["reasoning_content"]
    except Exception:
        return {"ok": False, "error": "bad completion", "raw": str(body)[:400], "v1": v1}
    return {"ok": True, "text": text, "usage": body.get("usage") or {}, "v1": v1}


def _has_launch(ep: dict) -> bool:
    launch = ep.get("launch")
    return isinstance(launch, dict) and bool(launch.get("bin") or launch.get("gguf"))


def prepare(ep: dict, start: bool = True) -> dict:
    """Make one endpoint ready. llama.cpp may be auto-started; others are ping-only."""
    ep = dict(ep)
    if _has_launch(ep):
        found = llama.discover()
        if found.get("ok"):
            ep["base_url"] = found.get("v1") or llama.v1_url(found["base_url"])
            return {"ok": True, "endpoint": ep, "already": True, "port": found.get("port")}
        if not start:
            return {"ok": False, "error": found.get("error") or "llama.cpp 未在监听", "endpoint": ep}
        started = llama.serve()
        if not started.get("ok"):
            return {**started, "endpoint": ep}
        ep["base_url"] = started.get("v1") or llama.v1_url(started.get("base_url") or "")
        return {"ok": True, "endpoint": ep, "started": True, "port": started.get("port")}
    hit = ping(ep)
    hit["endpoint"] = ep
    return hit


def complete(messages: list[dict], start: bool = True) -> dict:
    """Write via the first working /v1 endpoint. llama.cpp first, then backups."""
    cfg = load()
    tried = []
    for ep in endpoints():
        if not (ep.get("base_url") or "").strip() and not _has_launch(ep):
            continue
        ready = prepare(ep, start=start)
        tag = ep.get("id") or ep.get("base_url") or "?"
        if not ready.get("ok"):
            tried.append({"id": tag, "stage": "prepare", "error": ready.get("error")})
            continue
        live = ready["endpoint"]
        result = _chat(live, messages, cfg)
        if result.get("ok"):
            result["via"] = tag
            result["port"] = ready.get("port")
            return result
        tried.append({"id": tag, "stage": "chat", "error": result.get("error"), "v1": result.get("v1")})
    return {"ok": False, "error": "没有可用写稿 API", "tried": tried}


def status() -> dict:
    """Ping every endpoint. Does not start llama.cpp."""
    rows = []
    for ep in endpoints():
        row = {
            "id": ep.get("id") or "",
            "v1": v1_url(ep["base_url"]) if (ep.get("base_url") or "").strip() else "",
            "launch": _has_launch(ep),
            "model": ep.get("model") or "",
        }
        if not row["v1"] and not row["launch"]:
            row["ok"] = False
            row["error"] = "未配置"
            rows.append(row)
            continue
        if row["launch"]:
            found = llama.discover()
            row["ok"] = bool(found.get("ok"))
            if found.get("ok"):
                row["v1"] = found.get("v1") or llama.v1_url(found["base_url"])
                row["port"] = found.get("port")
            else:
                row["error"] = found.get("error")
                nxt = llama.pick_port()
                row["next_port"] = nxt.get("port")
                row["skipped"] = nxt.get("skipped") or []
        else:
            hit = ping(ep)
            row["ok"] = bool(hit.get("ok"))
            if hit.get("ok"):
                row["models"] = hit.get("models") or []
            else:
                row["error"] = hit.get("error")
        rows.append(row)
    return {"ok": True, "cmd": "api", "endpoints": rows}
