# -*- coding: utf-8 -*-
"""
Тесты асинхронных бэкендов хранения.

Redis-клиент подменяется фейком: реальный сервер в CI не нужен, а поведение
(Lua INCR+EXPIRE, prefix, декодирование байтов) проверяется как есть.
"""

import asyncio
import json

import pytest

from kremle_detect.storage import MemoryStorage
from kremle_detect.storage_async import AsyncRedisStorage, AsyncStorageAdapter, _run_sync


def run(coro):
    return asyncio.run(coro)


class TestRunSync:
    def test_wraps_function(self):
        assert run(_run_sync(lambda a, b: a + b, 1, 2)) == 3

    def test_propagates_exceptions(self):
        def boom():
            raise ValueError('nope')

        with pytest.raises(ValueError):
            run(_run_sync(boom))


class TestAsyncAdapter:
    def test_set_get_delete(self):
        adapter = AsyncStorageAdapter(MemoryStorage())

        async def scenario():
            await adapter.set('k', {'a': 1}, 60)
            assert await adapter.get('k') == {'a': 1}
            await adapter.delete('k')
            assert await adapter.get('k') is None

        run(scenario())

    def test_counters(self):
        adapter = AsyncStorageAdapter(MemoryStorage())

        async def scenario():
            assert await adapter.increment('c', 60) == 1
            assert await adapter.increment('c', 60) == 2
            assert await adapter.increment('forever') == 1
            assert await adapter.get_counter('c') == 2

        run(scenario())

    def test_blacklist_and_log(self):
        adapter = AsyncStorageAdapter(MemoryStorage())

        async def scenario():
            await adapter.blacklist_add('1.2.3.4', 60)
            assert await adapter.blacklist_check('1.2.3.4') is True
            assert await adapter.whitelist_check('1.2.3.4') is False
            await adapter.log_event({'event': 'pass'})
            assert adapter.sync.log_get(5)[0]['event'] == 'pass'

        run(scenario())

    def test_sync_property(self):
        storage = MemoryStorage()
        assert AsyncStorageAdapter(storage).sync is storage


class FakeAsyncRedis:
    """Минимальный асинхронный Redis-фейк для AsyncRedisStorage."""

    def __init__(self):
        self.data = {}
        self.eval_calls = []
        self.closed = False

    async def setex(self, key, ttl, value):
        self.data[key] = (value, ttl)

    async def set(self, key, value):
        self.data[key] = (value, None)

    async def get(self, key):
        item = self.data.get(key)
        return None if item is None else item[0].encode()

    async def delete(self, key):
        self.data.pop(key, None)

    async def incr(self, key):
        current = int(self.data.get(key, ('0', None))[0]) + 1
        self.data[key] = (str(current), None)
        return current

    async def eval(self, script, numkeys, key, ttl):
        self.eval_calls.append((key, ttl))
        current = int(self.data.get(key, ('0', None))[0]) + 1
        self.data[key] = (str(current), ttl if current == 1 else None)
        return current

    async def exists(self, key):
        return 1 if key in self.data else 0

    class _Pipe:
        def __init__(self, parent):
            self.parent = parent
            self.ops = []

        def lpush(self, key, value):
            self.ops.append((key, value))
            return self

        def ltrim(self, key, start, end):
            return self

        async def execute(self):
            for key, value in self.ops:
                self.parent.data.setdefault(key, ([], None))
                self.parent.data[key][0].insert(0, value)

    def pipeline(self):
        return self._Pipe(self)

    async def aclose(self):
        self.closed = True


class TestAsyncRedis:
    def make(self):
        fake = FakeAsyncRedis()
        return AsyncRedisStorage(redis_client=fake, prefix='kremle:'), fake

    def test_roundtrip(self):
        storage, fake = self.make()

        async def scenario():
            await storage.set('k', {'a': 1}, 60)
            assert fake.data['kremle:k'][0] == json.dumps({'a': 1}, ensure_ascii=False)
            assert await storage.get('k') == {'a': 1}
            await storage.delete('k')
            assert await storage.get('k') is None

        run(scenario())

    def test_increment_with_ttl_uses_lua(self):
        storage, fake = self.make()

        async def scenario():
            assert await storage.increment('rate:1', 60) == 1
            assert await storage.increment('rate:1', 60) == 2
            assert fake.eval_calls[0] == ('kremle:rate:1', 60)

        run(scenario())

    def test_increment_without_ttl(self):
        storage, fake = self.make()

        async def scenario():
            assert await storage.increment('stats:requests') == 1
            assert fake.eval_calls == []

        run(scenario())

    def test_counter_parsing(self):
        storage, fake = self.make()
        fake.data['kremle:c'] = ('42', None)

        async def scenario():
            assert await storage.get_counter('c') == 42
            assert await storage.get_counter('missing') == 0
            fake.data['kremle:bad'] = ('nope', None)
            assert await storage.get_counter('bad') == 0

        run(scenario())

    def test_blacklist_and_whitelist(self):
        storage, fake = self.make()

        async def scenario():
            await storage.blacklist_add('1.2.3.4', 60)
            await storage.whitelist_add('5.6.7.8')
            assert await storage.blacklist_check('1.2.3.4') is True
            assert await storage.whitelist_check('5.6.7.8') is True
            assert await storage.blacklist_check('5.6.7.8') is False
            # ttl<=0 не должен создавать вечную запись через setex(0)
            await storage.blacklist_add('9.9.9.9', 0)
            assert fake.data['kremle:blacklist:9.9.9.9'][1] > 0

        run(scenario())

    def test_log_event(self):
        storage, fake = self.make()

        async def scenario():
            await storage.log_event({'event': 'pass', 'ip': '1.2.3.4'})
            entry = fake.data['kremle:events'][0][0]
            assert json.loads(entry)['event'] == 'pass'

        run(scenario())

    def test_aclose(self):
        storage, fake = self.make()
        run(storage.aclose())
        assert fake.closed is True

    def test_requires_url_or_client(self):
        with pytest.raises(ValueError, match='url'):
            AsyncRedisStorage()
