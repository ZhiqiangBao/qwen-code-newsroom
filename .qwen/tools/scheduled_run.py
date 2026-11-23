"""Windows task entry point for precollection and candidate generation."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import edition
import publish


ROOT = Path(__file__).resolve().parents[2]
CHINA_TIME = timezone(timedelta(hours=8))
RETRY_DELAY = 600
REQUIRED_TOOLS = {"plan", "writer_status", "select", "copy_lineup", "compose", "prepare", "review"}
TRANSIENT_TYPE = {"NetworkError", "APIConnectionError", "APIConnectionTimeoutError", "ServiceUnavailableError", "RateLimitError"}
TRANSIENT_CODES = {"ETIMEDOUT", "ECONNRESET", "EAI_AGAIN", "ENETUNREACH", "UND_ERR_CONNECT_TIMEOUT"}


class FailedRun(Exception):
    def __init__(self, message: str, *, retryable: bool = False, process_exit: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.process_exit = process_exit


def now() -> datetime:
    return datetime.now(CHINA_TIME)


def resolve_edition(value: str | None, collect: bool) -> str:
    if value is not None:
        return edition.issue_date(value).isoformat()
    today = now().date()
    monday = today - timedelta(days=today.weekday())
    return (monday + timedelta(days=7) if collect else monday).isoformat()


class Journal:
    def __init__(self, stamp: str, mode: str):
        started = now()
        folder = ROOT / "schedule" / stamp
        folder.mkdir(parents=True, exist_ok=True)
        self.path = Path(tempfile.mkdtemp(prefix=f"{started:%Y%m%d-%H%M%S}-{mode}-", dir=folder))
        self.began = time.monotonic()
        self.data = {"edition": stamp, "mode": mode, "started_at": started.isoformat(), "attempt": 0}
        self.record("startup")

    def record(self, stage: str, status: str = "running", **fields) -> None:
        self.data.update(stage=stage, status=status, updated_at=now().isoformat(),
                         elapsed_seconds=round(time.monotonic() - self.began), **fields)
        tmp = self.path / "run.json.tmp"
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path / "run.json")


@contextmanager
def edition_lock(stamp: str):
    import msvcrt

    path = ROOT / "schedule" / stamp / "edition.lock"
    # Keep the file name stable. Windows releases the byte-range lock when the process exits.
    with path.open("a+b") as handle:
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise FailedRun("本刊期另有任务正在运行") from exc
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def command(argv: list[str], journal: Journal, name: str, timeout: float, *, request: str | None = None) -> tuple[int, Path, Path]:
    stdout = journal.path / f"{name}.stdout.log"
    stderr = journal.path / f"{name}.stderr.log"
    with stdout.open("wb") as out, stderr.open("wb") as err:
        child = subprocess.Popen(argv, cwd=ROOT, stdin=subprocess.PIPE if request is not None else subprocess.DEVNULL,
                                 stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            child.communicate(input=request.encode("utf-8") if request is not None else None, timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            if child.poll() is None:
                subprocess.run(["taskkill.exe", "/PID", str(child.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=15,
                               creationflags=subprocess.CREATE_NO_WINDOW)
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=10)
            raise
    return child.returncode, stdout, stderr


def last_record(path: Path) -> dict:
    with path.open("rb") as stream:
        offset = max(0, path.stat().st_size - 131_072)
        stream.seek(offset)
        tail = stream.read().decode("utf-8", errors="replace")
        if not offset:
            try:
                value = json.loads(tail)
            except ValueError:
                pass
            else:
                return value if isinstance(value, dict) else {}
        for line in reversed(tail.splitlines()):
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                return value
    return {}


def mcp_check(journal: Journal, attempt: int) -> None:
    config = json.loads((ROOT / ".qwen" / "settings.json").read_text(encoding="utf-8"))
    allowed = set(config["mcpServers"]["desk"]["includeTools"])
    requests = [
        {"id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                                                 "clientInfo": {"name": "monday-times", "version": "1"}}},
        {"method": "notifications/initialized"},
        {"id": 2, "method": "tools/list", "params": {}},
    ]
    request = "".join(json.dumps({"jsonrpc": "2.0", **msg}) + "\n" for msg in requests)
    code, out, _ = command([sys.executable, "-B", ".qwen/mcp/server.py"], journal, f"mcp-{attempt}", 20, request=request)
    reply = last_record(out)
    names = {tool["name"] for tool in reply.get("result", {}).get("tools", [])}
    if code or reply.get("id") != 2 or not REQUIRED_TOOLS <= names & allowed:
        raise FailedRun("MCP 无法提供完整的候选编审工具", process_exit=code)


def collect(journal: Journal, stamp: str, attempt: int) -> dict:
    journal.record("collect", attempt=attempt)
    code, out, _ = command([sys.executable, "-B", ".qwen/tools/desk.py", "collect", "--date", stamp],
                           journal, f"collect-{attempt}", 100)
    result = last_record(out)
    if result.get("date") != stamp or result.get("ok") is not True or code:
        temporary = any(source.get("status") == "network_error" or source.get("http") in {408, 429, 500, 502, 503, 504}
                        for source in result.get("sources", []))
        raise FailedRun("固定来源采集未返回可用结果", retryable=temporary, process_exit=code)
    statuses: dict[str, int] = {}
    for source in result.get("sources", []):
        state = source["status"]
        statuses[state] = statuses.get(state, 0) + 1
    counts = result.get("counts", {})
    return {"outcome": "sources_available" if any(counts.values()) else "no_items",
            "counts": counts, "source_statuses": statuses}


def preflight(args, journal: Journal, attempt: int) -> None:
    journal.record("runtime", attempt=attempt)
    for path in (args.node, args.qwen_cli, args.writer_config):
        if not path or not Path(path).is_file():
            raise FailedRun("缺少 Node、Qwen CLI 或写稿配置文件")
    code, _, _ = command([args.node, args.qwen_cli, "--version"], journal, f"qwen-version-{attempt}", 25)
    if code:
        raise FailedRun("Qwen CLI 启动失败", process_exit=code)
    journal.record("mcp")
    mcp_check(journal, attempt)
    journal.record("writer")
    probe = "import api,json; print(json.dumps(api.preflight(), ensure_ascii=False))"
    code, out, _ = command([sys.executable, "-B", "-c", "import sys; sys.path.insert(0,'.qwen/tools'); " + probe],
                           journal, f"writer-{attempt}", 45)
    result = last_record(out)
    if code or result.get("ok") is not True:
        raise FailedRun("写稿端点预检失败", retryable=result.get("kind") == "transient", process_exit=code)


def transient_qwen_exit(out: Path, err: Path) -> bool:
    for path in (out, err):
        record = last_record(path)
        error = record.get("error")
        if isinstance(error, dict) and (error.get("type") in TRANSIENT_TYPE or error.get("code") in TRANSIENT_CODES):
            return True
        if isinstance(error, dict) and error.get("status") in {408, 429, 500, 502, 503, 504}:
            return True
    return False


def candidate(args, journal: Journal, stamp: str, attempt: int, deadline: float) -> dict:
    existing = publish.reviewed_status(ROOT, stamp)
    if existing.get("ok"):
        return {"outcome": "reused", "fingerprint": existing["fingerprint"], "index": existing["index"]}
    preflight(args, journal, attempt)
    budget = int(deadline - time.monotonic())
    if budget < 60:
        raise FailedRun("本次运行时间已用尽")
    journal.record("candidate")
    brief = (ROOT / "weekly_prompt.txt").read_text(encoding="utf-8")
    prompt = f"刊头日期：{stamp}\n\n{brief}"
    code, out, err = command([args.node, args.qwen_cli, "-p", prompt, "--approval-mode", "auto-edit",
                              "--max-wall-time", f"{budget}s", "--max-tool-calls", "400", "--output-format", "json"],
                             journal, f"qwen-{attempt}", budget + 20)
    journal.record("candidate_review", process_exit=code)
    result = publish.reviewed_status(ROOT, stamp)
    if not result.get("ok"):
        reason = result.get("error") or "Qwen 异常退出"
        failure = f"候选校验未通过：{reason}" if not code else f"Qwen 退出且无可用候选：{reason}"
        raise FailedRun(failure, retryable=bool(code and transient_qwen_exit(out, err)), process_exit=code)
    return {"outcome": "candidate_ready", "fingerprint": result["fingerprint"], "index": result["index"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="星期时报定时任务")
    parser.add_argument("--date")
    parser.add_argument("--mode", choices=("collect", "candidate", "check"), default="candidate")
    parser.add_argument("--node")
    parser.add_argument("--qwen-cli")
    parser.add_argument("--writer-config")
    args = parser.parse_args()
    stamp = resolve_edition(args.date, args.mode == "collect")
    if args.writer_config:
        os.environ["MONDAY_TIMES_WRITER_CONFIG"] = str(Path(args.writer_config).resolve())
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), os.environ.get("PATH", "")])
    journal = Journal(stamp, args.mode)
    deadline = time.monotonic() + (25 * 60 if args.mode == "collect" else 4 * 60 * 60)
    try:
        with edition_lock(stamp):
            for attempt in (1, 2):
                journal.record("startup", attempt=attempt, process_exit=None)
                try:
                    if args.mode == "collect":
                        outcome = collect(journal, stamp, attempt)
                    elif args.mode == "check":
                        preflight(args, journal, attempt)
                        outcome = {"outcome": "dependencies_ready"}
                    else:
                        outcome = candidate(args, journal, stamp, attempt, deadline)
                except FailedRun as exc:
                    if not exc.retryable or attempt == 2 or args.mode == "check" or time.monotonic() + RETRY_DELAY + 60 >= deadline:
                        raise
                    journal.record("retry_wait", retry_delay_seconds=RETRY_DELAY,
                                   previous_error=str(exc), process_exit=exc.process_exit)
                    time.sleep(RETRY_DELAY)
                    continue
                journal.record("complete", "succeeded", exit_code=0, **outcome)
                break
    except subprocess.TimeoutExpired:
        journal.record(journal.data["stage"], "timed_out", exit_code=124, error="子进程超过运行时限")
    except KeyboardInterrupt:
        journal.record(journal.data["stage"], "interrupted", exit_code=130, error="任务收到控制中断")
    except (FailedRun, OSError, ValueError, KeyError) as exc:
        journal.record(journal.data["stage"], "failed", exit_code=1, error=str(exc),
                       process_exit=getattr(exc, "process_exit", None))
    print(json.dumps({**journal.data, "log": str(journal.path)}, ensure_ascii=True))
    return journal.data["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
