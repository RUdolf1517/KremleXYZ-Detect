# -*- coding: utf-8 -*-
"""
Тесты на живом Redis (маркер ``redis``).

Фейковый клиент не проверяет Lua, TTL и гонки — а именно там живут самые
неприятные баги (ключ без TTL, потерянный счётчик). Нужен настоящий сервер:

    docker run --rm -p 6379:6379 redis:7
    pytest -m redis

Адрес задаётся ``KREMLE_TEST_REDIS_URL`` (по умолчанию
``redis://localhost:6379/15``, база 15 — чтобы не трогать чужие данные).
Без Redis тесты скипаются, обычный ``pytest tests/`` остаётся зелёным.

Если сервер поднять негде (ноутбук, песочница), разрешён in-memory двойник:

    KREMLE_TEST_REDIS_FAKE=1 pytest -m redis -p no:cacheprovider

Он проверяет тот же код (Lua, TTL, префиксы), но не сеть и не гонки процессов —
поэтому в CI всё-таки настоящий сервис ``redis``.
"""

import json
import os
import time
import uuid

import pytest

redis = pytest.importorskip('redis', reason='redis-py не установлен')

pytestmark = pytest.mark.redis

REDIS_URL = os.environ.get('KREMLE_TEST_REDIS_URL', 'redis://localhost:6379/15')


@pytest.fixture(scope='module')
def live_redis():
    client = redis.from_url(REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except Exception as exc:  # noqa: BLE001 — нет сервера = скип, а не падение
        if os.environ.get('KREMLE_TEST_REDIS_FAKE') != '1':
            pytest.skip(f'Redis недоступен ({REDIS_URL}): {exc}')
        fake = pytest.importorskip('fakeredis', reason='fakeredis не установлен')
        client = fake.FakeRedis(decode_responses=True)
    yield client
    try:
        client.flushdb()
    except Exception:  # noqa: BLE001
        pass
    client.close()


@pytest.fixture
def prefix(live_redis):
    """Уникальный префикс — тесты не мешают друг другу и не сорят в базе."""
    value = f'kremle-test:{uuid.uuid4().hex[:8]}:'
    yield value
    for key in live_redis.scan_iter(f'{value}*'):
        live_redis.delete(key)


@pytest.fixture
def storage(live_redis, prefix):
    from kremle_detect.storage import RedisStorage
    return RedisStorage(redis_client=live_redis, prefix=prefix)


class TestRedisStorageLive:
    def test_set_get_delete(self, storage, live_redis, prefix):
        storage.set('k', {'a': 1}, 60)
        assert storage.get('k') == {'a': 1}
        assert live_redis.ttl(f'{prefix}k') > 0

        storage.delete('k')
        assert storage.get('k') is None

    def test_unicode_payload(self, storage):
        storage.set('ru', {'q': 'Сколько будет 2+2?', 'opts': ['4', '5']}, 60)
        assert storage.get('ru')['q'] == 'Сколько будет 2+2?'

    def test_increment_with_ttl_sets_expire_once(self, storage, live_redis, prefix):
        assert storage.increment('rate:1.2.3.4', ttl=60) == 1
        ttl_first = live_redis.ttl(f'{prefix}rate:1.2.3.4')
        assert ttl_first > 0

        time.sleep(0.05)
        assert storage.increment('rate:1.2.3.4', ttl=60) == 2
        # fixed window: TTL не сдвигается повторными инкрементами
        assert live_redis.ttl(f'{prefix}rate:1.2.3.4') <= ttl_first

    def test_increment_without_ttl_never_expires(self, storage, live_redis, prefix):
        """Счётчики метрик не должны исчезать через сутки."""
        storage.increment('stats:requests', ttl=None)
        storage.increment('stats:requests', ttl=None)
        assert storage.get_counter('stats:requests') == 2
        assert live_redis.ttl(f'{prefix}stats:requests') == -1

    def test_counter_survives_value_change(self, storage):
        storage.increment('c', ttl=60)
        assert storage.get_counter('c') == 1
        assert storage.get_counter('missing') == 0

    def test_blacklist_ttl(self, storage, live_redis, prefix):
        storage.blacklist_add('203.0.113.9', ttl=60)
        assert storage.blacklist_check('203.0.113.9') is True
        assert 0 < live_redis.ttl(f'{prefix}blacklist:203.0.113.9') <= 60

        storage.blacklist_remove('203.0.113.9')
        assert storage.blacklist_check('203.0.113.9') is False

    def test_blacklist_forever(self, storage, live_redis, prefix):
        """ttl=0 — «навсегда», но ключ всё равно должен жить без TTL-ошибки."""
        storage.blacklist_add('203.0.113.10', ttl=0)
        assert storage.blacklist_check('203.0.113.10') is True
        assert live_redis.ttl(f'{prefix}blacklist:203.0.113.10') != 0

    def test_whitelist(self, storage):
        storage.whitelist_add('198.51.100.1')
        assert storage.whitelist_check('198.51.100.1') is True
        storage.whitelist_remove('198.51.100.1')
        assert storage.whitelist_check('198.51.100.1') is False

    def test_event_log_ring(self, live_redis, prefix):
        from kremle_detect.storage import RedisStorage
        storage = RedisStorage(redis_client=live_redis, prefix=prefix)
        for i in range(5):
            storage.log_event({'event': 'pass', 'ip': f'10.0.0.{i}', 'ts': i})
        events = storage.log_get(3)
        assert len(events) == 3
        assert events[0]['ip'] == '10.0.0.4'   # новые сверху

    def test_listing_scans_prefix(self, storage, live_redis, prefix):
        storage.blacklist_add('10.1.1.1', ttl=60)
        storage.blacklist_add('10.1.1.2', ttl=60)
        assert sorted(storage.blacklist_list()) == ['10.1.1.1', '10.1.1.2']

        storage.whitelist_add('10.2.2.2')
        assert storage.whitelist_list() == ['10.2.2.2']


async def make_async_client():
    """
    Асинхронный клиент: настоящий ``redis.asyncio`` или его in-memory двойник.

    Создаётся **внутри** того же event loop, в котором будет использоваться.
    `redis.asyncio` привязывает соединение к циклу при первом запросе: клиент,
    «прогретый» в другом (или уже закрытом) цикле, падает с
    ``RuntimeError: another coroutine is already waiting for incoming data``.
    """
    from redis import asyncio as aioredis

    client = aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        await client.ping()
        return client
    except Exception as exc:  # noqa: BLE001
        await close_async(client)
        if os.environ.get('KREMLE_TEST_REDIS_FAKE') != '1':
            pytest.skip(f'Redis недоступен ({REDIS_URL}): {exc}')
        import fakeredis.aioredis
        return fakeredis.aioredis.FakeRedis(decode_responses=True)


async def close_async(client):
    """Закрывает клиент в том же цикле (redis-py 5+ — ``aclose``)."""
    closer = getattr(client, 'aclose', None) or getattr(client, 'close', None)
    if closer is None:
        return
    try:
        result = closer()
        if hasattr(result, '__await__'):
            await result
    except Exception:  # noqa: BLE001 — закрытие не должно ронять тест
        pass


class TestAsyncRedisLive:
    def test_async_roundtrip(self, prefix):
        import asyncio

        from kremle_detect.storage_async import AsyncRedisStorage

        async def scenario():
            client = await make_async_client()
            try:
                storage = AsyncRedisStorage(redis_client=client, prefix=prefix)

                await storage.set('k', {'a': 1}, 60)
                assert await storage.get('k') == {'a': 1}
                assert await storage.increment('c', 60) == 1
                assert await storage.increment('c', 60) == 2
                await storage.log_event({'event': 'shadow', 'ip': '1.2.3.4'})
                assert await storage.blacklist_check('1.2.3.4') is False
                await storage.blacklist_add('1.2.3.4', 60)
                assert await storage.blacklist_check('1.2.3.4') is True
            finally:
                await close_async(client)

        asyncio.run(scenario())

    def test_async_increment_ttl(self, prefix):
        import asyncio

        from kremle_detect.storage_async import AsyncRedisStorage

        async def scenario():
            client = await make_async_client()
            try:
                storage = AsyncRedisStorage(redis_client=client, prefix=prefix)

                # TTL читаем тем же (асинхронным) клиентом: с in-memory двойником
                # синхронный и асинхронный клиенты — разные «серверы»
                await storage.increment('rate:x', 30)
                assert 0 < await client.ttl(f'{prefix}rate:x') <= 30

                await storage.increment('forever')
                assert await client.ttl(f'{prefix}forever') == -1

                await storage.set('k', {'a': 1}, 60)
                assert await client.ttl(f'{prefix}k') > 0

                # Lua: TTL ставится только на первом инкременте (fixed window)
                ttl_first = await client.ttl(f'{prefix}rate:x')
                await storage.increment('rate:x', 30)
                assert await client.ttl(f'{prefix}rate:x') <= ttl_first
            finally:
                await close_async(client)

        asyncio.run(scenario())


class TestEngineOnRedis:
    def test_full_captcha_cycle(self, storage):
        from kremle_detect import CaptchaEngine

        engine = CaptchaEngine(
            categories=['math'], question_count=3, max_errors=1,
            secret='live-test', storage=storage,
        )
        challenge = engine.create_challenge()
        answers = {str(i): q['ans'] for i, q in enumerate(challenge.questions)}
        result = engine.verify(challenge.token, answers, ip='203.0.113.7')
        assert result['passed'] is True

        # токен одноразовый — даже в Redis
        again = engine.verify(challenge.token, answers, ip='203.0.113.7')
        assert again['error'] == 'invalid_token'

    def test_rate_limit_uses_real_incr(self, storage):
        from kremle_detect import CaptchaEngine

        engine = CaptchaEngine(
            categories=['math'], question_count=2, max_errors=0,
            secret='live-test', storage=storage, rate_limit=2, rate_window=600,
        )
        for _ in range(2):
            challenge = engine.create_challenge()
            engine.verify(challenge.token, {'0': 99, '1': 99}, ip='203.0.113.8')

        blocked = engine.verify('nope', {}, ip='203.0.113.8')
        assert blocked['error'] == 'rate_limited'

    def test_challenge_ttl(self, engine_storage_pair):
        engine, live_redis, prefix = engine_storage_pair
        challenge = engine.create_challenge()
        ttl = live_redis.ttl(f'{prefix}challenge:{challenge.token}')
        assert 0 < ttl <= 15 * 60 + 5

    def test_payload_is_json(self, engine_storage_pair):
        engine, live_redis, prefix = engine_storage_pair
        challenge = engine.create_challenge()
        raw = live_redis.get(f'{prefix}challenge:{challenge.token}')
        data = json.loads(raw)
        assert data['token'] == challenge.token
        assert 'answers' not in data


@pytest.fixture
def engine_storage_pair(storage, live_redis, prefix):
    from kremle_detect import CaptchaEngine
    engine = CaptchaEngine(
        categories=['math'], question_count=2, max_errors=1,
        secret='live-test', storage=storage,
    )
    return engine, live_redis, prefix


class TestTtlApi:
    """storage.ttl(): None — ключа нет, 0 — бессрочный, иначе остаток."""

    def test_memory_storage(self):
        from kremle_detect.storage import MemoryStorage
        storage = MemoryStorage()
        assert storage.ttl('missing') is None

        storage.blacklist_add('10.0.0.1', ttl=0)
        assert storage.ttl('blacklist:10.0.0.1') == 0   # «навсегда»

        storage.blacklist_add('10.0.0.2', ttl=120)
        remaining = storage.ttl('blacklist:10.0.0.2')
        assert 0 < remaining <= 120

    def test_redis_storage(self, storage):
        assert storage.ttl('missing') is None
        storage.blacklist_add('10.1.0.1', ttl=0)
        assert storage.ttl('blacklist:10.1.0.1') == 0
        storage.blacklist_add('10.1.0.2', ttl=120)
        assert 0 < storage.ttl('blacklist:10.1.0.2') <= 120
