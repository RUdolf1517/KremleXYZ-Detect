# -*- coding: utf-8 -*-
"""
Асинхронные бэкенды хранения.

Зачем: FastAPI-интеграция вызывает движок капчи из ``async def``. Синхронный
Redis-клиент блокирует event loop на время сетевого запроса. Два способа
этого избежать:

1. ``AsyncRedisStorage`` — нативный asyncio-клиент (``redis.asyncio``),
   без threadpool.
2. ``AsyncStorageAdapter`` — обёртка над любым синхронным ``BaseStorage``;
   операции уходят в threadpool. Подходит, если уже есть свой бэкенд.

Оба реализуют один и тот же интерфейс, поэтому:

    storage = AsyncRedisStorage(url='redis://localhost:6379/0')
    await storage.set('k', {'a': 1}, 60)
    await storage.get('k')
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

from .storage import BaseStorage

try:  # anyio есть у FastAPI/Starlette; при использовании отдельно — fallback
    from anyio import to_thread
except ImportError:  # pragma: no cover
    to_thread = None


async def _run_sync(func, *args, **kwargs):
    """Выполняет синхронную функцию в threadpool (или напрямую, если anyio нет)."""
    if to_thread is None:  # pragma: no cover
        return func(*args, **kwargs)
    return await to_thread.run_sync(lambda: func(*args, **kwargs))


class AsyncStorageAdapter:
    """
    Async-обёртка над синхронным ``BaseStorage``.

    Пример:
        adapter = AsyncStorageAdapter(MemoryStorage())
        await adapter.increment('rate:ip', 60)
    """

    def __init__(self, storage: BaseStorage):
        self._storage = storage

    @property
    def sync(self) -> BaseStorage:
        """Исходное синхронное хранилище (его ждёт CaptchaEngine)."""
        return self._storage

    async def set(self, key: str, value: dict, ttl: int) -> None:
        await _run_sync(self._storage.set, key, value, ttl)

    async def get(self, key: str) -> Optional[dict]:
        return await _run_sync(self._storage.get, key)

    async def delete(self, key: str) -> None:
        await _run_sync(self._storage.delete, key)

    async def increment(self, key: str, ttl: Optional[int] = None) -> int:
        return await _run_sync(self._storage.increment, key, ttl)

    async def get_counter(self, key: str) -> int:
        return await _run_sync(self._storage.get_counter, key)

    async def blacklist_add(self, ip: str, ttl: int) -> None:
        await _run_sync(self._storage.blacklist_add, ip, ttl)

    async def blacklist_check(self, ip: str) -> bool:
        return await _run_sync(self._storage.blacklist_check, ip)

    async def whitelist_check(self, ip: str) -> bool:
        return await _run_sync(self._storage.whitelist_check, ip)

    async def log_event(self, event: dict) -> None:
        await _run_sync(self._storage.log_event, event)


_INCR_WITH_TTL_LUA = """
local v = redis.call('INCR', KEYS[1])
if v == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return v
"""


class AsyncRedisStorage:
    """
    Нативный asyncio Redis-бэкенд (``pip install redis``, redis-py ≥ 4.2).

    Пример:
        storage = AsyncRedisStorage(url='redis://localhost:6379/0')
        await storage.set('challenge:token', data, 900)
        await storage.aclose()

    Для ``CaptchaEngine`` (синхронного) используйте ``RedisStorage``.
    """

    _LOG_KEY = 'events'
    _LOG_MAX = 1000

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
                from redis.asyncio import from_url
            except ImportError as exc:  # pragma: no cover
                raise ImportError(
                    'Для асинхронного Redis нужен redis-py ≥ 4.2: pip install "redis>=4.2"'
                ) from exc
            self._redis = from_url(url, decode_responses=True)
        else:
            raise ValueError('Укажите url или redis_client')
        self._prefix = prefix

    def _key(self, key: str) -> str:
        return f'{self._prefix}{key}'

    async def set(self, key: str, value: dict, ttl: int) -> None:
        # set(..., ex=) вместо setex: setex помечен deprecated в redis-py 6
        payload = json.dumps(value, ensure_ascii=False)
        if ttl and ttl > 0:
            await self._redis.set(self._key(key), payload, ex=ttl)
        else:
            await self._redis.set(self._key(key), payload)

    async def get(self, key: str) -> Optional[dict]:
        raw = await self._redis.get(self._key(key))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode()
        return json.loads(raw)

    async def delete(self, key: str) -> None:
        await self._redis.delete(self._key(key))

    async def increment(self, key: str, ttl: Optional[int] = None) -> int:
        rk = self._key(key)
        if ttl is None:
            return int(await self._redis.incr(rk))
        return int(await self._redis.eval(_INCR_WITH_TTL_LUA, 1, rk, int(ttl)))

    async def get_counter(self, key: str) -> int:
        raw = await self._redis.get(self._key(key))
        if raw is None:
            return 0
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    async def blacklist_add(self, ip: str, ttl: int) -> None:
        await self._redis.set(
            self._key(f'blacklist:{ip}'),
            json.dumps({'ip': ip}),
            ex=ttl if ttl > 0 else 86400 * 365 * 10,
        )

    async def blacklist_check(self, ip: str) -> bool:
        return await self._redis.exists(self._key(f'blacklist:{ip}')) == 1

    async def whitelist_check(self, ip: str) -> bool:
        return await self._redis.exists(self._key(f'whitelist:{ip}')) == 1

    async def whitelist_add(self, ip: str) -> None:
        await self._redis.set(
            self._key(f'whitelist:{ip}'), json.dumps({'ip': ip}), ex=86400 * 365 * 10
        )

    async def log_event(self, event: dict) -> None:
        rk = self._key(self._LOG_KEY)
        pipe = self._redis.pipeline()
        pipe.lpush(rk, json.dumps(event, ensure_ascii=False))
        pipe.ltrim(rk, 0, self._LOG_MAX - 1)
        await pipe.execute()

    async def aclose(self) -> None:
        """Закрыть соединения (для тестов и graceful shutdown)."""
        close = getattr(self._redis, 'aclose', None) or getattr(self._redis, 'close', None)
        if close is None:
            return
        result = close()
        if asyncio.iscoroutine(result):
            await result
