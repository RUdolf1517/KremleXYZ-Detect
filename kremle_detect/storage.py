# -*- coding: utf-8 -*-
"""
Бэкенды хранения челленджей: Memory и Redis.

Memory — для разработки (один процесс).
Redis  — для продакшена (несколько воркеров/серверов).
"""

from __future__ import annotations

import collections
import json
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseStorage(ABC):
    """Абстрактный бэкенд хранения."""

    @abstractmethod
    def set(self, key: str, value: dict, ttl: int) -> None:
        """Сохранить данные с TTL в секундах."""

    @abstractmethod
    def get(self, key: str) -> Optional[dict]:
        """Получить данные по ключу. None если нет или истёк."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Удалить по ключу."""

    @abstractmethod
    def increment(self, key: str, ttl: int) -> int:
        """Инкремент счётчика. Возвращает новое значение. TTL ставится при создании."""

    def blacklist_add(self, ip: str, ttl: int) -> None:
        """Добавить IP в чёрный список на ttl секунд (0 = навсегда)."""
        self.set(f'blacklist:{ip}', {'ip': ip}, ttl if ttl > 0 else 86400 * 365 * 10)

    def blacklist_check(self, ip: str) -> bool:
        """True если IP в чёрном списке."""
        return self.get(f'blacklist:{ip}') is not None

    def blacklist_remove(self, ip: str) -> None:
        """Убрать IP из чёрного списка."""
        self.delete(f'blacklist:{ip}')

    def blacklist_list(self) -> list:
        """Список всех IP в чёрном списке."""
        return []  # переопределяется в подклассах

    # ── Whitelist (persistent, managed via CLI / engine API) ──────────────

    _WHITELIST_TTL = 86400 * 365 * 10  # 10 лет ≈ «навсегда»

    def whitelist_add(self, ip: str) -> None:
        """Добавить IP в белый список навсегда."""
        self.set(f'whitelist:{ip}', {'ip': ip}, self._WHITELIST_TTL)

    def whitelist_check(self, ip: str) -> bool:
        """True если IP в белом списке."""
        return self.get(f'whitelist:{ip}') is not None

    def whitelist_remove(self, ip: str) -> None:
        """Убрать IP из белого списка."""
        self.delete(f'whitelist:{ip}')

    def whitelist_list(self) -> list:
        """Список всех IP в белом списке."""
        return []  # переопределяется в подклассах

    # ── Event log (ring buffer) ───────────────────────────────────────────

    _LOG_KEY = 'events'
    _LOG_MAX = 1000  # хранить последние N событий

    def log_event(self, event: dict) -> None:
        """Записать событие в ring buffer. По умолчанию — no-op."""

    def log_get(self, n: int = 100) -> list:
        """Получить последние n событий (новые первыми)."""
        return []


_CLEANUP_INTERVAL = 60  # секунд между принудительными очистками


class MemoryStorage(BaseStorage):
    """In-memory хранение (один процесс). По умолчанию."""

    def __init__(self):
        self._data: Dict[str, tuple] = {}  # key → (value, expires_at)
        self._last_cleanup: float = time.time()
        self._events: collections.deque = collections.deque(maxlen=self._LOG_MAX)

    def set(self, key: str, value: dict, ttl: int) -> None:
        self._data[key] = (value, time.time() + ttl)
        self._cleanup()

    def get(self, key: str) -> Optional[dict]:
        entry = self._data.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.time() > expires_at:
            del self._data[key]
            return None
        return value

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def increment(self, key: str, ttl: int) -> int:
        entry = self._data.get(key)
        if entry is None or time.time() > entry[1]:
            self._data[key] = ({'count': 1}, time.time() + ttl)
            return 1
        val = entry[0]
        val['count'] = val.get('count', 0) + 1
        return val['count']

    def blacklist_list(self) -> list:
        now = time.time()
        prefix = 'blacklist:'
        return [
            k[len(prefix):]
            for k, (_, exp) in list(self._data.items())
            if k.startswith(prefix) and now <= exp
        ]

    def whitelist_list(self) -> list:
        now = time.time()
        prefix = 'whitelist:'
        return [
            k[len(prefix):]
            for k, (_, exp) in list(self._data.items())
            if k.startswith(prefix) and now <= exp
        ]

    def log_event(self, event: dict) -> None:
        self._events.appendleft(event)

    def log_get(self, n: int = 100) -> list:
        return list(self._events)[:n]

    def _cleanup(self) -> None:
        """Удаляем просроченные записи не чаще раза в минуту."""
        now = time.time()
        if now - self._last_cleanup < _CLEANUP_INTERVAL:
            return
        self._last_cleanup = now
        expired = [k for k, (_, exp) in self._data.items() if now > exp]
        for k in expired:
            del self._data[k]


class RedisStorage(BaseStorage):
    """
    Redis-бэкенд. Работает с несколькими воркерами/серверами.

    Args:
        url: Redis URL (например 'redis://localhost:6379/0')
        redis_client: готовый redis.Redis объект (альтернатива url)
        prefix: префикс ключей в Redis
    """

    def __init__(
        self,
        url: Optional[str] = None,
        redis_client: Any = None,
        prefix: str = 'kremle:',
    ):
        if redis_client is not None:
            self._redis = redis_client
        elif url is not None:
            try:
                import redis
            except ImportError:
                raise ImportError(
                    'Для Redis-бэкенда нужна библиотека redis: pip install redis'
                )
            self._redis = redis.from_url(url)
        else:
            raise ValueError('Укажите url или redis_client')
        self._prefix = prefix

    def _key(self, key: str) -> str:
        return f'{self._prefix}{key}'

    def set(self, key: str, value: dict, ttl: int) -> None:
        self._redis.setex(self._key(key), ttl, json.dumps(value, ensure_ascii=False))

    def get(self, key: str) -> Optional[dict]:
        raw = self._redis.get(self._key(key))
        if raw is None:
            return None
        return json.loads(raw)

    def delete(self, key: str) -> None:
        self._redis.delete(self._key(key))

    def increment(self, key: str, ttl: int) -> int:
        rk = self._key(key)
        pipe = self._redis.pipeline()
        pipe.incr(rk)
        result = pipe.execute()
        count = result[0]
        # Set TTL only when the key is newly created (count == 1).
        # Calling expire() on every increment would extend the window on each request
        # (sliding window bug). Fixed window: TTL is set once at creation.
        if count == 1:
            self._redis.expire(rk, ttl)
        return count

    def _scan_suffix(self, ns: str) -> list:
        """Вернуть всё что идёт после kremle:{ns}: для найденных ключей."""
        pattern = self._key(f'{ns}:*')
        prefix = self._key(f'{ns}:')
        result = []
        for raw in self._redis.scan_iter(pattern):
            key = raw.decode() if isinstance(raw, bytes) else raw
            result.append(key[len(prefix):])
        return result

    def blacklist_list(self) -> list:
        return self._scan_suffix('blacklist')

    def whitelist_list(self) -> list:
        return self._scan_suffix('whitelist')

    def log_event(self, event: dict) -> None:
        rk = self._key(self._LOG_KEY)
        pipe = self._redis.pipeline()
        pipe.lpush(rk, json.dumps(event, ensure_ascii=False))
        pipe.ltrim(rk, 0, self._LOG_MAX - 1)
        pipe.execute()

    def log_get(self, n: int = 100) -> list:
        rk = self._key(self._LOG_KEY)
        raw_list = self._redis.lrange(rk, 0, n - 1)
        result = []
        for raw in raw_list:
            try:
                result.append(json.loads(raw))
            except (ValueError, TypeError):
                pass
        return result
