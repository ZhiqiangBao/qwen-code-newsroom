"""Publish a reviewed candidate through the existing release entry point."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / ".qwen" / "tools"))

from publish import run  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="发行已终审的星期时报候选页")
    parser.add_argument("--date", required=True)
    parser.add_argument("--approve", required=True, help="终审通过的完整候选指纹")
    args = parser.parse_args()
    result = run(ROOT, args.date, approval=args.approve)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
