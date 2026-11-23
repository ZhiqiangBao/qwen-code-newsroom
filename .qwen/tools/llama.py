"""Start and find local llama-server. The copywriter talks to /v1 via api.py.

Port: preferred in writer.json launch, then 18080–18139. Occupied by other
apps (8080, 8090, …) are skipped. HTML on /health is not llama.
Live bind is recorded in .qwen/tmp/llama.runtime.json.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
RUNTIME = HERE.parent / "tmp" / "llama.runtime.json"
BAND = range(18080, 18140)
DEFAULTS = {
    "base_url": "http://127.0.0.1:18080",
    "model": "Gemma4-E2B",
    "bin": r"D:\Qwen\llama.cpp\llama-server.exe",
    "gguf": r"D:\Qwen\Gemma4-E2B\gemma-4-E2B-it-UD-Q8_K_XL.gguf",
    "ngl": 999,
    "ctx": 8192,
    "port": 18080,
    "timeout": 180,
    "host": "127.0.0.1",
    "extra": [],
}


def origin(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if "://" not in u:
        u = "http://" + u
    p = urlparse(u)
    host = p.hostname or "127.0.0.1"
    port = p.port
    scheme = p.scheme or "http"
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        return f"{scheme}://{host}:{port}"
    return f"{scheme}://{host}"


def v1_url(url: str) -> str:
    o = origin(url)
    return (o + "/v1") if o else ""


def writer_config_path() -> Path:
    override = os.environ.get("MONDAY_TIMES_WRITER_CONFIG", "").strip()
    return Path(override).expanduser() if override else HERE / "writer.json"


def load_cfg(root: Path | None = None) -> dict:
    cfg = dict(DEFAULTS)
    old = HERE / "llama.json"
    if old.is_file():
        cfg.update(json.loads(old.read_text(encoding="utf-8")))
    writer = writer_config_path()
    if os.environ.get("MONDAY_TIMES_WRITER_CONFIG", "").strip() and not writer.is_file():
        raise FileNotFoundError("writer config override does not exist")
    if writer.is_file():
        data = json.loads(writer.read_text(encoding="utf-8"))
        if data.get("timeout"):
            cfg["timeout"] = data["timeout"]
        for ep in data.get("endpoints") or []:
            launch = ep.get("launch") if isinstance(ep, dict) else None
            if not isinstance(launch, dict):
                continue
            if not (launch.get("bin") or launch.get("gguf")):
                continue
            cfg.update(launch)
            if ep.get("base_url"):
                cfg["base_url"] = origin(ep["base_url"])
            if ep.get("model"):
                cfg["model"] = ep["model"]
            break
    if cfg.get("base_url"):
        cfg["base_url"] = origin(cfg["base_url"])
    return cfg


def _read_runtime() -> dict:
    if not RUNTIME.is_file():
        return {}
    try:
        return json.loads(RUNTIME.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_runtime(port: int, base_url: str, pid: int | None = None) -> None:
    o = origin(base_url)
    RUNTIME.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME.write_text(
        json.dumps(
            {"port": port, "base_url": o, "origin": o, "v1": v1_url(o), "pid": pid},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _get_json(url: str, timeout: float = 1.0) -> dict | None:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(8000)
        text = raw.decode("utf-8", "replace").lstrip()
        if not text or text.startswith("<"):
            return None
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _is_llama(base_url: str) -> dict | None:
    o = origin(base_url)
    if not o:
        return None
    models = _get_json(v1_url(o) + "/models")
    if models and ("data" in models or models.get("object") == "list"):
        return {"ok": True, "path": "/v1/models", "models": models, "v1": v1_url(o)}
    health = _get_json(o + "/health")
    if not health:
        return None
    if health.get("status") in ("ok", "healthy") or "slots" in health:
        return {"ok": True, "path": "/health", "health": health, "v1": v1_url(o)}
    return None


def listening(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        return s.connect_ex((host, int(port))) == 0


def _uniq_ports(ports) -> list[int]:
    seen: list[int] = []
    for p in ports:
        p = int(p)
        if 1024 <= p <= 65535 and p not in seen:
            seen.append(p)
    return seen


def _bind_ports(cfg: dict) -> list[int]:
    """Ports we may start llama on. Never 8080/8090 — those belong to other apps."""
    preferred = int(cfg.get("port") or 18080)
    return _uniq_ports([preferred, *BAND])


def _scan_ports(cfg: dict) -> list[int]:
    """Peek at foreign ports plus the preferred bind port. Do not walk the whole band."""
    extra = [int(p) for p in (cfg.get("scan") or [])]
    preferred = int(cfg.get("port") or 18080)
    return _uniq_ports([*extra, preferred])


def _port_of(url: str) -> int | None:
    o = origin(url)
    if not o:
        return None
    p = urlparse(o)
    if p.port:
        return p.port
    if p.scheme == "https":
        return 443
    return 80


def _host_of(url: str) -> str:
    return (urlparse(origin(url) or url).hostname or "127.0.0.1").lower()


def discover(cfg: dict | None = None) -> dict:
    """Find a live llama-server. Only probe ports that are actually listening."""
    cfg = cfg or load_cfg()
    tried = []
    urls: list[str] = []
    rt = _read_runtime()
    if rt.get("base_url"):
        urls.append(rt["base_url"])
    if cfg.get("base_url"):
        urls.append(cfg["base_url"])
    for p in _scan_ports(cfg):
        urls.append(f"http://127.0.0.1:{p}")
    seen: set[str] = set()
    for url in urls:
        url = (url or "").rstrip("/")
        if not url or url in seen:
            continue
        seen.add(url)
        port = _port_of(url)
        host = _host_of(url)
        if port is None:
            continue
        if host in ("127.0.0.1", "localhost") and not listening(port, host="127.0.0.1"):
            continue
        tried.append(v1_url(url) or url)
        hit = _is_llama(url)
        if hit:
            o = origin(url)
            _write_runtime(port, o)
            return {"ok": True, "base_url": o, "origin": o, "v1": v1_url(o), "port": port, **hit}
    return {"ok": False, "error": "llama-server 未在监听", "tried": tried[:12]}


def ping(cfg: dict | None = None) -> dict:
    return discover(cfg)


def pick_port(cfg: dict | None = None) -> dict:
    """First free port in the newspaper band. Busy ports (any app) are skipped."""
    cfg = cfg or load_cfg()
    skipped = []
    for p in _bind_ports(cfg):
        if listening(p):
            kind = "llama" if _is_llama(f"http://127.0.0.1:{p}") else "other"
            skipped.append({"port": p, "who": kind})
            continue
        return {"ok": True, "port": p, "skipped": skipped}
    return {"ok": False, "error": "18080–18139 都被占", "skipped": skipped}


def chat(messages: list[dict], cfg: dict | None = None) -> dict:
    """llama.cpp only. Copywriter should call api.complete so backups work."""
    cfg = cfg or load_cfg()
    found = discover(cfg)
    if found.get("ok"):
        cfg = dict(cfg)
        cfg["base_url"] = found["base_url"]
        cfg["port"] = found["port"]
    payload = {
        "model": cfg.get("model") or "local",
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 3500,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        v1_url(cfg["base_url"]) + "/chat/completions",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=int(cfg.get("timeout") or 180)) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"http {e.code}", "detail": e.read()[:400].decode("utf-8", "replace")}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    try:
        text = body["choices"][0]["message"]["content"] or ""
    except Exception:
        return {"ok": False, "error": "bad completion", "raw": str(body)[:400]}
    return {"ok": True, "text": text, "usage": body.get("usage") or {}}


def serve(cfg: dict | None = None) -> dict:
    cfg = cfg or load_cfg()
    alive = discover(cfg)
    if alive.get("ok"):
        return {
            "ok": True,
            "already": True,
            "base_url": alive["base_url"],
            "v1": alive.get("v1") or v1_url(alive["base_url"]),
            "port": alive["port"],
        }
    gguf = (cfg.get("gguf") or "").strip()
    bin_name = cfg.get("bin") or "llama-server"
    if not gguf:
        return {
            "ok": False,
            "error": "llama.cpp 未启动，且 writer.json 未写 launch.gguf",
            "hint": "在 endpoints[0].launch 写 gguf/bin，或先手动启动 llama-server",
        }
    picked = pick_port(cfg)
    if not picked.get("ok"):
        return picked
    port = int(picked["port"])
    host = cfg.get("host") or "127.0.0.1"
    extra = [str(x) for x in (cfg.get("extra") or [])]
    cmd = [
        bin_name,
        "-m",
        gguf,
        "--host",
        host,
        "--port",
        str(port),
        "-c",
        str(cfg.get("ctx") or 8192),
        "-ngl",
        str(cfg.get("ngl") or 99),
        *extra,
    ]
    cwd = str(Path(bin_name).parent) if Path(bin_name).is_file() else str(HERE)
    try:
        proc = subprocess.Popen(cmd, cwd=cwd)
    except FileNotFoundError:
        return {"ok": False, "error": f"找不到 {bin_name}", "hint": "writer.json launch.bin 写成绝对路径"}
    base_url = f"http://{host}:{port}"
    for _ in range(90):
        time.sleep(1.5)
        if _is_llama(base_url):
            _write_runtime(port, base_url, proc.pid)
            return {
                "ok": True,
                "started": True,
                "port": port,
                "base_url": base_url,
                "v1": v1_url(base_url),
                "pid": proc.pid,
                "skipped": picked.get("skipped") or [],
            }
        if proc.poll() is not None:
            return {"ok": False, "error": f"进程退出 code={proc.returncode}", "cmd": cmd, "port": port}
    return {"ok": False, "error": "已拉起进程但 /v1/models 未就绪", "cmd": cmd, "port": port, "pid": proc.pid}
