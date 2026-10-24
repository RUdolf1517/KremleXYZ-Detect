# -*- coding: utf-8 -*-
"""
Счётчики и health-check.

Метрики лежат в том же хранилище, что и челленджи (Memory/Redis), поэтому
работают и в одном процессе, и в кластере с Redis. Набор счётчиков фиксирован:
так снапшот читается без сканирования ключей.
"""

from __future__ import annotations

import time
from typing import Dict, Optional

from .policy import ACTIONS, DEFAULT_POLICY
from .storage import BaseStorage

# Детерминированный порядок — удобно для Prometheus-выдачи и тестов.
REASONS = tuple(DEFAULT_POLICY.keys())
BLOCK_REASONS = ('blacklisted', 'rate_limited')

_TOTAL_REQUESTS = 'requests'
_TOTAL_DETECTED = 'detected'
_TOTAL_ALLOWED = 'allowed'


class Metrics:
    """
    Счётчики событий в хранилище.

    Пример:
        m = Metrics(storage)
        m.count_request()
        m.count_detect('yandex_browser', action='monitor')
        m.snapshot()['detected_total']   # → 1
    """

    def __init__(self, storage: BaseStorage, enabled: bool = True):
        self.storage = storage
        self.enabled = enabled

    # ── запись ───────────────────────────────────────────────────────────────

    def _inc(self, key: str, value: int = 1) -> None:
        if not self.enabled or value <= 0:
            return
        # ttl=None → счётчик не истекает (монотонный, как у Prometheus)
        for _ in range(value):
            self.storage.increment(f'stats:{key}', ttl=None)

    def count_request(self) -> None:
        """Каждый запрос, прошедший через гард."""
        self._inc(_TOTAL_REQUESTS)

    def count_detect(self, reason: str, action: str) -> None:
        """Детекция сигнала + принятое действие."""
        self._inc(f'{_TOTAL_DETECTED}:{reason}')
        if action in ACTIONS:
            self._inc(f'action:{action}')

    def count_allow(self) -> None:
        """Запрос без сигналов — пропущен (виден и в ``actions.allow``)."""
        self._inc(_TOTAL_ALLOWED)
        self._inc('action:allow')

    def count_challenge(self) -> None:
        """Выдан челлендж."""
        self._inc('challenge_issued')

    def count_verify(self) -> None:
        """Проверка ответов."""
        self._inc('verify')

    def count_pass(self) -> None:
        self._inc('pass')

    def count_fail(self) -> None:
        self._inc('fail')

    def count_blocked(self, reason: str) -> None:
        self._inc(f'blocked:{reason}')

    # ── чтение ───────────────────────────────────────────────────────────────

    def _get(self, key: str) -> int:
        return self.storage.get_counter(f'stats:{key}')

    def snapshot(self) -> Dict[str, object]:
        """
        Плоский снапшот для JSON-эндпоинта.

        Пример:
            {
              'requests_total': 120,
              'detected_total': 37,
              'allowed_total': 83,
              'detected_by_reason': {'yandex_browser': 30, ...},
              'actions': {'challenge': 10, 'monitor': 27, ...},
              'challenges_issued': 10,
              'verify_total': 9,
              'pass_total': 6,
              'fail_total': 3,
              'blocked_by_reason': {'blacklisted': 0, 'rate_limited': 0},
              'pass_rate': 0.67,
              'ts': 1700000000.0,
            }
        """
        detected = {reason: self._get(f'{_TOTAL_DETECTED}:{reason}') for reason in REASONS}
        actions = {action: self._get(f'action:{action}') for action in ACTIONS}
        blocked = {reason: self._get(f'blocked:{reason}') for reason in BLOCK_REASONS}
        verify = self._get('verify')
        passed = self._get('pass')
        failed = self._get('fail')

        return {
            'requests_total': self._get(_TOTAL_REQUESTS),
            'detected_total': sum(detected.values()),
            'allowed_total': self._get(_TOTAL_ALLOWED),
            'detected_by_reason': detected,
            'actions': actions,
            'shadow_total': actions.get('monitor', 0),
            'challenges_issued': self._get('challenge_issued'),
            'verify_total': verify,
            'pass_total': passed,
            'fail_total': failed,
            'blocked_by_reason': blocked,
            'pass_rate': round(passed / verify, 4) if verify else None,
            'ts': time.time(),
        }

    def prometheus(self) -> str:
        """
        Текст в формате Prometheus (text exposition format 0.0.4).

        Пример строки:
            kremle_detected_total{reason="yandex_browser"} 30
        """
        snap = self.snapshot()
        lines = [
            '# HELP kremle_requests_total Запросы, прошедшие через гард',
            '# TYPE kremle_requests_total counter',
            f'kremle_requests_total {snap["requests_total"]}',
            '# HELP kremle_allowed_total Запросы без сигналов',
            '# TYPE kremle_allowed_total counter',
            f'kremle_allowed_total {snap["allowed_total"]}',
            '# HELP kremle_detected_total Детекции по причинам',
            '# TYPE kremle_detected_total counter',
        ]
        for reason, value in snap['detected_by_reason'].items():
            lines.append(f'kremle_detected_total{{reason="{reason}"}} {value}')
        lines += [
            '# HELP kremle_action_total Принятые действия политики',
            '# TYPE kremle_action_total counter',
        ]
        for action, value in snap['actions'].items():
            lines.append(f'kremle_action_total{{action="{action}"}} {value}')
        lines += [
            '# HELP kremle_challenges_total Выдано челленджей',
            '# TYPE kremle_challenges_total counter',
            f'kremle_challenges_total {snap["challenges_issued"]}',
            '# HELP kremle_verify_total Проверок ответов',
            '# TYPE kremle_verify_total counter',
            f'kremle_verify_total {snap["verify_total"]}',
            '# HELP kremle_captcha_total Результаты прохождения капчи',
            '# TYPE kremle_captcha_total counter',
            f'kremle_captcha_total{{result="pass"}} {snap["pass_total"]}',
            f'kremle_captcha_total{{result="fail"}} {snap["fail_total"]}',
            '# HELP kremle_blocked_total Блокировки по причинам',
            '# TYPE kremle_blocked_total counter',
        ]
        for reason, value in snap['blocked_by_reason'].items():
            lines.append(f'kremle_blocked_total{{reason="{reason}"}} {value}')
        return '\n'.join(lines) + '\n'


def health_payload(
    version: str,
    storage: Optional[BaseStorage] = None,
    storage_name: str = 'memory',
    extra: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """
    Ответ /kremle/health.

    Проверяет, что хранилище отвечает на чтение/запись — этого достаточно,
    чтобы отличить «живой» процесс от зависшего.
    """
    storage_ok = True
    if storage is not None:
        probe_key = 'health:probe'
        try:
            storage.set(probe_key, {'ts': time.time()}, 60)
            storage_ok = storage.get(probe_key) is not None
            storage.delete(probe_key)
        except Exception:  # noqa: BLE001 — health не должен падать из-за бэкенда
            storage_ok = False

    payload: Dict[str, object] = {
        'status': 'ok' if storage_ok else 'degraded',
        'version': version,
        'storage': storage_name,
        'storage_ok': storage_ok,
        'ts': time.time(),
    }
    if extra:
        payload.update(extra)
    return payload
