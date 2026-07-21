#!/usr/bin/env python3
"""CLI-обёртка: печатает crontab из env (для docker/cron-entrypoint.sh)."""

from __future__ import annotations

import sys

from explainlaw.cron_schedule import render_crontab


def main() -> int:
    sys.stdout.write(render_crontab())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
