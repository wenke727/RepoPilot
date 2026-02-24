#!/usr/bin/env python3
from __future__ import annotations

import argparse
import time
from pathlib import Path


def cleanup(logs_dir: Path, retention_days: int) -> int:
    if retention_days <= 0:
        return 0

    deleted = 0
    cutoff = time.time() - retention_days * 24 * 3600
    for file_path in logs_dir.glob('*.ndjson'):
        if file_path.stat().st_mtime < cutoff:
            file_path.unlink(missing_ok=True)
            deleted += 1
    return deleted


def main() -> int:
    default_logs_dir = Path(__file__).resolve().parents[1] / 'state' / 'logs'
    parser = argparse.ArgumentParser(description='Cleanup old task logs')
    parser.add_argument('--logs-dir', default=str(default_logs_dir))
    parser.add_argument('--retention-days', type=int, default=30)
    args = parser.parse_args()

    logs_dir = Path(args.logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)
    deleted = cleanup(logs_dir, args.retention_days)
    print(f'deleted={deleted}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
