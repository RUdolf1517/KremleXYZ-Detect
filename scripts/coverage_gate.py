#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Гейт покрытия по модулям: один общий порог скрывает провалы в отдельных файлах.

Общий `--cov-fail-under=85` устраивает только до тех пор, пока кто-то не
добавит триста строк в один файл и не покроет их наполовину: суммарный процент
не шевельнётся. Поэтому у модулей, где ошибка стоит дорого, свой порог.

Запуск:

    python -m pytest tests/ --cov=kremle_detect --cov-report=json
    python scripts/coverage_gate.py                    # пороги из pyproject.toml
    python scripts/coverage_gate.py --report c.json    # другой отчёт

Пороги лежат в `pyproject.toml` секции `[tool.kremle.coverage]`:

    [tool.kremle.coverage]
    overall = 90
    "kremle_detect/storage.py" = 95

Код возврата 1, если хоть один порог не выполнен — CI красит джоб, а сообщение
перечисляет ровно те файлы, что просели.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

DEFAULT_REPORT = 'coverage.json'
DEFAULT_CONFIG = 'pyproject.toml'


def _load_toml(path: str) -> dict:
    """tomllib в 3.11+, tomli до него. Без обеих библиотек — внятная ошибка."""
    try:
        import tomllib  # type: ignore[import-not-found]
    except ModuleNotFoundError:  # pragma: no cover - зависит от версии Python
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ModuleNotFoundError:  # pragma: no cover
            raise SystemExit(
                'Нужен tomllib (Python 3.11+) или tomli: pip install tomli'
            ) from None
    with open(path, encoding='utf-8') as f:
        return tomllib.loads(f.read())


def _load_targets(path: str) -> tuple:
    """(общий порог | None, {файл: порог})."""
    if not os.path.exists(path):
        raise SystemExit(f'Нет конфига: {path}')
    section = _load_toml(path).get('tool', {}).get('kremle', {}).get('coverage', {})
    overall = section.pop('overall', None)
    return overall, {name: float(value) for name, value in section.items()}


def _percent(entry: dict) -> float:
    summary = entry.get('summary') or {}
    if 'percent_covered' in summary:
        return float(summary['percent_covered'])
    statements = summary.get('num_statements', 0)
    missing = summary.get('missing_lines', 0)
    if not statements:
        return 100.0
    return 100.0 * (statements - missing) / statements


def check(report: dict, overall, targets: dict) -> list:
    """Список провалов: (что, факт, порог)."""
    failures = []
    files = report.get('files') or {}
    if overall is not None:
        actual = _percent({'summary': report.get('totals') or {}})
        if actual + 1e-9 < overall:
            failures.append(('всё вместе', actual, overall))
    for name, threshold in sorted(targets.items()):
        entry = files.get(name)
        if entry is None:
            failures.append((f'{name} (нет в отчёте)', 0.0, threshold))
            continue
        actual = _percent(entry)
        if actual + 1e-9 < threshold:
            failures.append((name, actual, threshold))
    return failures


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Гейт покрытия по модулям')
    parser.add_argument('--report', default=DEFAULT_REPORT,
                        help='JSON-отчёт coverage (по умолчанию coverage.json)')
    parser.add_argument('--config', default=DEFAULT_CONFIG,
                        help='откуда брать пороги (по умолчанию pyproject.toml)')
    args = parser.parse_args(argv)

    if not os.path.exists(args.report):
        print(f'Нет отчёта покрытия: {args.report}. Сначала прогоните pytest '
              f'с --cov-report=json.', file=sys.stderr)
        return 2

    overall, targets = _load_targets(args.config)
    with open(args.report, encoding='utf-8') as f:
        report = json.load(f)

    failures = check(report, overall, targets)
    for name, actual, threshold in failures:
        print(f'::error title=coverage::{name}: {actual:.1f} % < {threshold:.0f} %')
        print(f'  {name}: {actual:.1f} % < {threshold:.0f} %', file=sys.stderr)

    checked = len(targets) + (1 if overall is not None else 0)
    if failures:
        print(f'Гейт покрытия: провалено {len(failures)} из {checked}', file=sys.stderr)
        return 1
    print(f'Гейт покрытия: всё выше порогов ({checked} проверок)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
