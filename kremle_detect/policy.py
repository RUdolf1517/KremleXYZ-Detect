# -*- coding: utf-8 -*-
"""
Политика обработки сегментов трафика.

Вместо «всё или ничего» каждому сигналу детекции можно назначить действие:

============  ==========================================================
``challenge`` показать капчу (по умолчанию для всех сигналов)
``block``     сразу 403/429, без капчи
``monitor``   ничего не делать, только считать (shadow-режим)
``allow``     пропустить и не считать как нарушение
============  ==========================================================

Плюс ``sample_rate``: какая доля детектированных запросов реально получает
капчу. Остальные уходят в shadow-статистику — это позволяет включить
фильтр на 5–10% трафика и посмотреть, не разбегутся ли люди.
"""

from __future__ import annotations

from typing import Dict, Iterable, Mapping, Optional

CHALLENGE = 'challenge'
BLOCK = 'block'
MONITOR = 'monitor'
ALLOW = 'allow'

ACTIONS = (CHALLENGE, BLOCK, MONITOR, ALLOW)

DEFAULT_POLICY: Dict[str, str] = {
    'yandex_bot': CHALLENGE,
    'yandex_browser': CHALLENGE,
    'yandex_client_hints': CHALLENGE,
    'yandex_referrer': CHALLENGE,
}


def normalize_policy(policy: Optional[Mapping[str, str]]) -> Dict[str, str]:
    """
    Валидирует пользовательскую политику и дополняет её значениями по умолчанию.

    Пример:
        normalize_policy({'yandex_bot': 'block', 'yandex_referrer': 'monitor'})
        # → {'yandex_bot': 'block', 'yandex_browser': 'challenge',
        #    'yandex_client_hints': 'challenge', 'yandex_referrer': 'monitor'}
    """
    result = dict(DEFAULT_POLICY)
    if not policy:
        return result

    for reason, action in dict(policy).items():
        key = str(reason).strip()
        value = str(action).strip().lower()
        if value not in ACTIONS:
            raise ValueError(
                f'Неизвестное действие политики {action!r} для {key!r}. '
                f'Допустимые: {", ".join(ACTIONS)}'
            )
        result[key] = value
    return result


def validate_sample_rate(value) -> float:
    """sample_rate — число от 0 до 1."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'sample_rate должен быть числом от 0 до 1, получено {type(value).__name__}')
    rate = float(value)
    if not 0.0 <= rate <= 1.0:
        raise ValueError(f'sample_rate должен быть от 0 до 1, получено {value}')
    return rate


class Decision:
    """Что делать с конкретным запросом."""

    __slots__ = ('action', 'reason', 'sampled')

    def __init__(self, action: str, reason: Optional[str], sampled: bool = True):
        self.action = action
        self.reason = reason
        self.sampled = sampled

    @property
    def should_block(self) -> bool:
        return self.action in (CHALLENGE, BLOCK)

    @property
    def is_shadow(self) -> bool:
        return self.action == MONITOR

    def __bool__(self) -> bool:
        """True, если запрос нужно как-то обработать (не allow)."""
        return self.action != ALLOW

    def __repr__(self) -> str:
        return f'Decision(action={self.action!r}, reason={self.reason!r}, sampled={self.sampled})'

    def __eq__(self, other) -> bool:
        if not isinstance(other, Decision):
            return NotImplemented
        return (self.action, self.reason, self.sampled) == (other.action, other.reason, other.sampled)


def reasons_from_hits(browser: bool, bot: bool, referrer: bool, client_hints: bool) -> Iterable[str]:
    """Все сработавшие сигналы (в порядке приоритета), а не только главный."""
    if bot:
        yield 'yandex_bot'
    if browser:
        yield 'yandex_browser'
    if client_hints:
        yield 'yandex_client_hints'
    if referrer:
        yield 'yandex_referrer'
