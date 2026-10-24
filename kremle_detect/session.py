# -*- coding: utf-8 -*-
"""
Состояние «капча пройдена» и его срок жизни.

Раньше в сессии лежал просто флаг ``True`` — он жил до истечения cookie
(до 31 дня) и не сбрасывался. Теперь хранится словарь с меткой времени и
отпечатком клиента, а срок проверяется на каждом запросе.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Mapping, Optional

SESSION_KEY = 'kremle_ok'
NEXT_KEY = 'kremle_next'
TOKEN_KEY = 'kremle_token'

DEFAULT_VERIFIED_TTL = 86400  # сутки


def ua_fingerprint(ua: Optional[str]) -> str:
    """Короткий стабильный отпечаток User-Agent."""
    if not ua:
        return ''
    return hashlib.sha256(ua.encode('utf-8', 'replace')).hexdigest()[:16]


def build_verification(
    ip: Optional[str] = None,
    ua: Optional[str] = None,
    ttl: int = DEFAULT_VERIFIED_TTL,
) -> dict:
    """
    Новое состояние «пройдено» для сессии.

    Пример:
        session['kremle_ok'] = build_verification(ip='1.2.3.4', ua=request.headers['User-Agent'])
    """
    now = time.time()
    return {
        'ok': True,
        'ts': now,
        'exp': now + ttl if ttl > 0 else 0,   # 0 → бессрочно
        'ip': ip or '',
        'ua': ua_fingerprint(ua),
    }


def is_verified(
    state: Any,
    ip: Optional[str] = None,
    ua: Optional[str] = None,
    bind_ip: bool = False,
    bind_ua: bool = False,
) -> bool:
    """
    Проверяет состояние из сессии.

    * ``state is True`` (старый формат) → считается просроченным:
      пользователь один раз перепройдёт капчу, зато TTL начнёт работать.
    * истёк ``exp`` → False;
    * изменился IP (при ``bind_ip``) или UA (при ``bind_ua``) → False.
    """
    if not isinstance(state, Mapping):
        return False
    if not state.get('ok'):
        return False

    exp = state.get('exp')
    if exp and time.time() > float(exp):
        return False

    if bind_ip and state.get('ip') and ip and state['ip'] != ip:
        return False

    if bind_ua:
        stored_ua = state.get('ua') or ''
        if stored_ua and stored_ua != ua_fingerprint(ua):
            return False

    return True


def remaining_seconds(state: Any) -> Optional[int]:
    """Сколько ещё действует прохождение (None — бессрочно или не пройдено)."""
    if not isinstance(state, Mapping) or not state.get('ok'):
        return None
    exp = state.get('exp') or 0
    if not exp:
        return None
    return max(0, int(float(exp) - time.time()))
