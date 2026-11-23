"""OpenAI-compatible /v1 client. Copywriter talks only to this.

Endpoints are tried in writer.json order. The first with a `launch` block
is llama.cpp: discover, then start, then POST /v1/chat/completions.
Later endpoints are already-running APIs (ollama, cloud, another llama).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import urllib.error
import urllib.request
from pathlib import Path

import llama

HERE = Path(__file__).resolve().parent
QWEN_SETTINGS = Path.home() / ".qwen" / "settings.json"


def load() -> dict:
    path = llama.writer_config_path()
    if os.environ.get("MONDAY_TIMES_WRITER_CONFIG", "").strip() and not path.is_file():
        raise FileNotFoundError("writer config override does not exist")
    if not path.is_file():
        return {"timeout": 180, "temperature": 0.3, "max_tokens": 3500, "endpoints": []}
    return json.loads(path.read_text(encoding="utf-8"))


def endpoints() -> list[dict]:
    return [dict(ep) for ep in (load().get("endpoints") or []) if isinstance(ep, dict)]


def v1_url(url: str) -> str:
    """Keep DashScope .../compatible-mode/v1. llama.cpp origin-only URLs still get /v1."""
    u = (url or "").strip().rstrip("/")
    if not u:
        return ""
    if "/v1" in u.split("://", 1)[-1]:
        return u
    return llama.v1_url(u)


def _qwen_env(name: str) -> str:
    if not name or not QWEN_SETTINGS.is_file():
        return ""
    try:
        env = json.loads(QWEN_SETTINGS.read_text(encoding="utf-8")).get("env") or {}
    except Exception:
        return ""
    return str(env.get(name) or "").strip()


def _secret(ep: dict) -> str:
    name = (ep.get("api_key_env") or "").strip()
    return (
        (os.environ.get(name) or "").strip()
        or str(ep.get("api_key") or "").strip()
        or _qwen_env(name)
    )


def _headers(ep: dict) -> dict:
    headers = {"Content-Type": "application/json"}
    key = _secret(ep)
    if key:
        headers["Authorization"] = "Bearer " + key
    return headers


def _get_json(url: str, headers: dict | None = None, timeout: float = 8) -> dict | None:
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


THINK_RE = re.compile(r"<think>[\s\S]*?</think>", re.I)


def _visible_text(msg: dict) -> str:
    """Newspaper copy is message.content only. Never use reasoning_content."""
    text = (msg.get("content") or "").strip()
    return THINK_RE.sub("", text).strip()


def _post_chat(v1: str, payload: dict, headers: dict, timeout: int):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        v1 + "/chat/completions",
        data=data,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _openai_client(ep: dict, timeout: int):
    from openai import OpenAI

    return OpenAI(
        api_key=_secret(ep) or "x",
        base_url=v1_url(ep.get("base_url") or ""),
        timeout=timeout,
    )


def _chat_openai(ep: dict, messages: list[dict], cfg: dict) -> dict:
    """DashScope compatible-mode via official OpenAI SDK.

    Thinking on: stream=True, extra_body enable_thinking True, keep delta.content.
    Thinking off: non-stream create, extra_body enable_thinking False.
    """
    v1 = v1_url(ep.get("base_url") or "")
    think = bool(ep.get("thinking"))
    timeout = int(cfg.get("timeout") or 180)
    client = _openai_client(ep, timeout)
    kwargs = {
        "model": ep.get("model") or "local",
        "messages": messages,
        "temperature": cfg.get("temperature", 0.3),
        "max_tokens": int(cfg.get("max_tokens") or 3500),
    }
    try:
        if think:
            completion = client.chat.completions.create(
                extra_body={"enable_thinking": True},
                stream=True,
                **kwargs,
            )
            parts: list[str] = []
            reasoning = False
            for chunk in completion:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if getattr(delta, "reasoning_content", None):
                    reasoning = True
                if getattr(delta, "content", None):
                    parts.append(delta.content)
            text = THINK_RE.sub("", "".join(parts)).strip()
            if not text:
                return {
                    "ok": False,
                    "error": "只有思考链、没有正文",
                    "v1": v1,
                    "reasoning": reasoning,
                }
            return {
                "ok": True,
                "text": text,
                "usage": {},
                "v1": v1,
                "reasoning": reasoning,
                "stream": True,
            }
        completion = client.chat.completions.create(
            extra_body={"enable_thinking": False},
            **kwargs,
        )
        msg = completion.choices[0].message
        text = _visible_text(
            {
                "content": msg.content or "",
                "reasoning_content": getattr(msg, "reasoning_content", None),
            }
        )
        usage = {}
        if completion.usage:
            usage = completion.usage.model_dump() if hasattr(completion.usage, "model_dump") else {}
        if not text:
            return {
                "ok": False,
                "error": "只有思考链、没有正文",
                "v1": v1,
                "reasoning": bool(getattr(msg, "reasoning_content", None)),
            }
        return {
            "ok": True,
            "text": text,
            "usage": usage,
            "v1": v1,
            "reasoning": bool(getattr(msg, "reasoning_content", None)),
            "stream": False,
        }
    except Exception as e:
        detail = getattr(e, "message", None) or str(e)
        return {"ok": False, "error": str(e), "detail": str(detail)[:400], "v1": v1}


def _chat_local(ep: dict, messages: list[dict], cfg: dict) -> dict:
    v1 = v1_url(ep.get("base_url") or "")
    timeout = int(cfg.get("timeout") or 180)
    payload = {
        "model": ep.get("model") or "local",
        "messages": messages,
        "temperature": cfg.get("temperature", 0.3),
        "max_tokens": int(cfg.get("max_tokens") or 3500),
        "enable_thinking": False,
    }
    try:
        body = _post_chat(v1, payload, _headers(ep), timeout)
    except urllib.error.HTTPError as e:
        return {
            "ok": False,
            "error": f"http {e.code}",
            "detail": e.read()[:400].decode("utf-8", "replace"),
            "v1": v1,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "v1": v1}
    try:
        msg = body["choices"][0]["message"]
        text = _visible_text(msg)
    except Exception:
        return {"ok": False, "error": "bad completion", "raw": str(body)[:400], "v1": v1}
    if not text:
        return {
            "ok": False,
            "error": "只有思考链、没有正文",
            "v1": v1,
            "reasoning": bool(msg.get("reasoning_content")),
        }
    return {
        "ok": True,
        "text": text,
        "usage": body.get("usage") or {},
        "v1": v1,
        "reasoning": bool((msg.get("reasoning_content") or "").strip()),
    }


def _chat(ep: dict, messages: list[dict], cfg: dict) -> dict:
    u = ep.get("base_url") or ""
    if _has_launch(ep) or "127.0.0.1" in u or "localhost" in u:
        return _chat_local(ep, messages, cfg)
    return _chat_openai(ep, messages, cfg)


def _has_launch(ep: dict) -> bool:
    launch = ep.get("launch")
    return isinstance(launch, dict) and bool(launch.get("bin") or launch.get("gguf"))


def prepare(ep: dict, start: bool = True) -> dict:
    """Make one endpoint ready. llama.cpp may be auto-started; others are ping-only."""
    ep = dict(ep)
    if _has_launch(ep):
        found = llama.discover()
        want = (ep.get("model") or "").strip()
        names = []
        models = found.get("models") if isinstance(found.get("models"), dict) else {}
        for it in models.get("data") or []:
            if isinstance(it, dict) and it.get("id"):
                names.append(it["id"])
        if found.get("ok") and (not want or want in names):
            ep["base_url"] = found.get("v1") or llama.v1_url(found["base_url"])
            return {"ok": True, "endpoint": ep, "already": True, "port": found.get("port"), "models": names}
        if found.get("ok") and want and want not in names:
            return {"ok": False, "error": f"本地服务模型 {names or '未知'} 与所需模型 {want} 不符；请手动处理", "endpoint": ep}
        elif not found.get("ok") and not start:
            return {"ok": False, "error": found.get("error") or "llama.cpp 未在监听", "endpoint": ep}
        started = llama.serve()
        if not started.get("ok"):
            return {**started, "endpoint": ep}
        ep["base_url"] = started.get("v1") or llama.v1_url(started.get("base_url") or "")
        return {"ok": True, "endpoint": ep, "started": True, "port": started.get("port")}
    hit = ping(ep)
    if hit.get("ok"):
        hit["endpoint"] = ep
        return hit
    if (ep.get("base_url") or "").strip() and _secret(ep):
        return {"ok": True, "endpoint": ep, "ping_skipped": hit.get("error")}
    hit["endpoint"] = ep
    return hit


def complete(messages: list[dict], start: bool = True, role: str = "ordinary") -> dict:
    """Write via the first working /v1 endpoint. llama.cpp first, then backups."""
    cfg = load()
    tried = []
    available = endpoints()
    # Explicit analysis endpoints are preferred only for analysis; normal work
    # uses the local/default route and never requires a remote service.
    if role == "analysis":
        preferred = [ep for ep in available if "analysis" in (ep.get("roles") or [])]
        available = preferred + [ep for ep in available if ep not in preferred
                                 and (not ep.get("roles") or "ordinary" in ep["roles"])]
    else:
        available = [ep for ep in available if not ep.get("roles") or "ordinary" in ep.get("roles", [])]
    for ep in available:
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


def preflight() -> dict:
    """Check ordinary writing routes without starting a local model or exposing credentials.

    A failure is transient when at least one eligible route has a temporary
    connection, rate limit, or server failure; otherwise it is a configuration
    or authentication failure. The caller may retry transient failures.
    """
    try:
        available = endpoints()
        rows = []
        for ep in available:
            roles = ep.get("roles") or []
            if roles and "ordinary" not in roles:
                continue
            tag = str(ep.get("id") or "endpoint")
            if _has_launch(ep):
                launch = llama.load_cfg()
                binary = str(launch.get("bin") or "")
                gguf = str(launch.get("gguf") or "")
                if (Path(binary).is_file() or shutil.which(binary)) and Path(gguf).is_file():
                    return {"ok": True, "endpoint": tag, "availability": "startable"}
                rows.append({"id": tag, "kind": "configuration", "error": "local model binary or GGUF missing"})
                continue
            base = str(ep.get("base_url") or "").strip()
            if not base:
                rows.append({"id": tag, "kind": "configuration", "error": "base_url missing"})
                continue
            try:
                request = urllib.request.Request(v1_url(base) + "/models", headers=_headers(ep), method="GET")
                with urllib.request.urlopen(request, timeout=8) as response:
                    obj = json.loads(response.read(8000).decode("utf-8"))
                if isinstance(obj, dict) and ("data" in obj or obj.get("object") == "list"):
                    return {"ok": True, "endpoint": tag, "availability": "reachable"}
                rows.append({"id": tag, "kind": "configuration", "error": "invalid models response"})
            except urllib.error.HTTPError as exc:
                kind = "transient" if exc.code == 429 or 500 <= exc.code <= 599 else "configuration"
                rows.append({"id": tag, "kind": kind, "error": f"http {exc.code}"})
            except (urllib.error.URLError, TimeoutError, OSError):
                rows.append({"id": tag, "kind": "transient", "error": "connection or timeout"})
            except (ValueError, UnicodeError):
                rows.append({"id": tag, "kind": "configuration", "error": "invalid endpoint or models response"})
        kind = "transient" if any(row["kind"] == "transient" for row in rows) else "configuration"
        return {"ok": False, "kind": kind, "error": "no available ordinary writing route", "endpoints": rows}
    except (OSError, ValueError, TypeError, AttributeError):
        return {"ok": False, "kind": "configuration", "error": "writer configuration invalid or unavailable"}


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
