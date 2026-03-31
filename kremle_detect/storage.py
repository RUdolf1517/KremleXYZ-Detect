# -*- coding: utf-8 -*-
"""
Бэкенды хранения челленджей: Memory и Redis.

Memory — для разработки (один процесс).
Redis  — для продакшена (несколько воркеров/серверов).
"""

from __future__ import annotations

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


class MemoryStorage(BaseStorage):
    """In-memory хранение (один процесс). По умолчанию."""

    def __init__(self):
        self._data: Dict[str, tuple] = {}  # key → (value, expires_at)

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

    def _cleanup(self) -> None:
        """Ленивая очистка — удаляем просроченные каждые 100 записей."""
        if len(self._data) % 100 != 0:
            return
        now = time.time()
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
        pipe.expire(rk, ttl)
        result = pipe.execute()
        return result[0]
