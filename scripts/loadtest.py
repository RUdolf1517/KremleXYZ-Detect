#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Нагрузочный смоук: сколько запросов в секунду и какая задержка.

Запуск (нужен поднятый демо-сервер: `kremle-detect serve`):

    python scripts/loadtest.py                     # 200 запросов, 20 потоков
    python scripts/loadtest.py -n 2000 -c 50
    python scripts/loadtest.py --url http://host:8000 --endpoint verify

Что измеряет:
    * обычный запрос (не-Яндекс UA) — «горячий путь» через гард;
    * запрос с Яндекс-UA — создание челленджа + 403/302;
    * полный цикл капчи: GET /kremle/challenge → POST /kremle/verify.

Зависимостей, кроме стандартной библиотеки, нет. Числа — для одного процесса
на песочнице; на реальном Redis и воркере будут другими, важен порядок.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, List

YANDEX_UA = 'Mozilla/5.0 (Windows NT 10.0) YaBrowser/24.1 Yowser/2.5 Safari/537.36'
NORMAL_UA = 'Mozilla/5.0 (Windows NT 10.0) Chrome/120.0 Safari/537.36'


@dataclass
class Stats:
    """Результаты одного прогона."""

    name: str
    latencies: List[float] = field(default_factory=list)
    errors: int = 0
    statuses: dict = field(default_factory=dict)
    wall_time: float = 0.0

    def add(self, seconds: float, status: int) -> None:
        self.latencies.append(seconds)
        self.statuses[status] = self.statuses.get(status, 0) + 1

    @property
    def count(self) -> int:
        return len(self.latencies)

    def percentile(self, p: float) -> float:
        if not self.latencies:
            return 0.0
        ordered = sorted(self.latencies)
        index = min(int(len(ordered) * p), len(ordered) - 1)
        return ordered[index]

    def report(self) -> str:
        rps = self.count / self.wall_time if self.wall_time else 0.0
        statuses = ', '.join(f'{k}:{v}' for k, v in sorted(self.statuses.items()))
        return (
            f'{self.name}\n'
            f'  запросов: {self.count}  за {self.wall_time:.2f} с  →  {rps:.0f} rps\n'
            f'  ошибок:   {self.errors}\n'
            f'  статусы:  {statuses}\n'
            f'  задержка: p50 {self.percentile(0.5) * 1000:.1f} ms · '
            f'p95 {self.percentile(0.95) * 1000:.1f} ms · '
            f'max {max(self.latencies, default=0) * 1000:.1f} ms\n'
            f'  среднее:  {statistics.mean(self.latencies) * 1000:.1f} ms'
            if self.latencies else f'{self.name}: нет данных'
        )


def http(method: str, url: str, *, data: dict = None, headers: dict = None,
         timeout: float = 10.0) -> tuple:
    """Возвращает (статус, тело). Ошибки сети → (0, текст ошибки)."""
    body = json.dumps(data).encode() if data is not None else None
    request = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    if body is not None:
        request.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except Exception as exc:  # noqa: BLE001 — нагрузочный смоук не должен падать
        return 0, str(exc).encode()


def run_workers(name: str, count: int, concurrency: int, action: Callable[[], int]) -> Stats:
    """Гоняет ``action`` в пуле потоков и собирает статистику."""
    stats = Stats(name)

    def task():
        started = time.perf_counter()
        try:
            status = action()
        except Exception:  # noqa: BLE001
            status = 0
        elapsed = time.perf_counter() - started
        if status == 0:
            stats.errors += 1
        stats.add(elapsed, status)
        return status

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(lambda _: task(), range(count)))
    stats.wall_time = time.perf_counter() - started
    return stats


def scenario_normal(base: str) -> Callable[[], int]:
    url = f'{base}/'
    def action() -> int:
        return http('GET', url, headers={'User-Agent': NORMAL_UA})[0]
    return action


def scenario_yandex(base: str) -> Callable[[], int]:
    """Яндекс-UA: челлендж создаётся, клиент получает 403 JSON."""
    url = f'{base}/api/me'
    def action() -> int:
        status, _ = http('GET', url, headers={
            'User-Agent': YANDEX_UA, 'Accept': 'application/json',
        })
        return status
    return action


def scenario_full_captcha(base: str) -> Callable[[], int]:
    """Полный цикл: challenge → verify (ответы угадываем — нам важна цена пути)."""
    challenge_url = f'{base}/kremle/challenge'
    verify_url = f'{base}/kremle/verify'

    def action() -> int:
        status, raw = http('GET', challenge_url, headers={
            'User-Agent': YANDEX_UA, 'Accept': 'application/json',
        })
        if status != 200:
            return status
        try:
            payload = json.loads(raw)
        except ValueError:
            return 0
        answers = {
            str(i): random.randrange(len(q['opts']))
            for i, q in enumerate(payload.get('questions', []))
        }
        status, _ = http('POST', verify_url, data={
            'token': payload['token'], 'answers': answers,
        }, headers={'User-Agent': YANDEX_UA})
        return status

    return action


SCENARIOS = {
    'normal': scenario_normal,
    'yandex': scenario_yandex,
    'verify': scenario_full_captcha,
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('-n', '--requests', type=int, default=200,
                        help='Запросов на сценарий (по умолч. 200)')
    parser.add_argument('-c', '--concurrency', type=int, default=20,
                        help='Потоков (по умолч. 20)')
    parser.add_argument('--url', default='http://127.0.0.1:8000', help='База демо-сервера')
    parser.add_argument('--endpoint', choices=['all', *SCENARIOS], default='all')
    args = parser.parse_args(argv)

    names = list(SCENARIOS) if args.endpoint == 'all' else [args.endpoint]
    failed = False

    for name in names:
        stats = run_workers(
            f'[{name}]', args.requests, args.concurrency, SCENARIOS[name](args.url),
        )
        print(stats.report())
        if stats.errors:
            failed = True

    print('\nПорядок величин ожидаем: память-хранилище — тысячи rps, '
          'Redis по сети — сотни. Если p95 выше ~100 ms на 20 потоках, '
          'смотрите хранилище и размер пула воркеров.')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
