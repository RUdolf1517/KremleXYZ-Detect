# -*- coding: utf-8 -*-
"""Тесты RedisStorage на фейковом клиенте (без живого Redis)."""

import json

import pytest

from kremle_detect.storage import MemoryStorage, RedisStorage


class FakePipeline:
    def __init__(self, client):
        self.client = client
        self.ops = []

    def incr(self, key):
        self.ops.append(('incr', key))
        return self

    def lpush(self, key, value):
        self.ops.append(('lpush', key, value))
        return self

    def ltrim(self, key, start, end):
        self.ops.append(('ltrim', key, start, end))
        return self

    def execute(self):
        out = []
        for op in self.ops:
            if op[0] == 'incr':
                out.append(self.client._incr(op[1]))
            elif op[0] == 'lpush':
                self.client.lpush(op[1], op[2])
                out.append(1)
            elif op[0] == 'ltrim':
                self.client.ltrim(op[1], op[2], op[3])
                out.append('OK')
        self.ops = []
        return out


class FakeRedis:
    """Минимальная реализация нужных команд."""

    def __init__(self, supports_eval=True):
        self.data = {}
        self.ttl = {}
        self.eval_calls = 0
        self.expire_calls = 0
        self.supports_eval = supports_eval

    # строки
    def setex(self, key, ttl, value):
        self.data[key] = value
        self.ttl[key] = ttl

    def set(self, key, value, ex=None):
        """ex=None — бессрочный ключ (blacklist/whitelist «навсегда»)."""
        self.data[key] = value
        if ex is None:
            self.ttl.pop(key, None)
        else:
            self.ttl[key] = ex

    def ttl_of(self, key):  # имя не ttl, чтобы не затенять словарь self.ttl
        return self.ttl.get(key)

    def get(self, key):
        return self.data.get(key)

    def delete(self, key):
        self.data.pop(key, None)
        self.ttl.pop(key, None)

    def _incr(self, key):
        self.data[key] = str(int(self.data.get(key, 0)) + 1)
        return int(self.data[key])

    def incr(self, key):
        return self._incr(key)

    def expire(self, key, ttl):
        self.expire_calls += 1
        self.ttl[key] = ttl

    def eval(self, script, numkeys, key, ttl):
        if not self.supports_eval:
            raise NotImplementedError('eval not available')
        self.eval_calls += 1
        value = self._incr(key)
        if value == 1:
            self.ttl[key] = ttl
        return value

    def pipeline(self):
        return FakePipeline(self)

    def scan_iter(self, pattern):
        prefix = pattern.rstrip('*')
        return [k.encode() for k in self.data if k.startswith(prefix)]

    def lpush(self, key, value):
        self.data.setdefault(key, [])
        self.data[key].insert(0, value)

    def ltrim(self, key, start, end):
        if isinstance(self.data.get(key), list):
            self.data[key] = self.data[key][:end + 1]

    def lrange(self, key, start, end):
        return self.data.get(key, [])[start:end + 1]


class TestChallenges:
    def test_set_get_roundtrip(self):
        client = FakeRedis()
        storage = RedisStorage(redis_client=client)
        storage.set('challenge:abc', {'a': 1, 'ru': 'тест'}, 60)
        assert storage.get('challenge:abc') == {'a': 1, 'ru': 'тест'}
        assert json.loads(client.data['kremle:challenge:abc'])['ru'] == 'тест'

    def test_prefix_isolation(self):
        client = FakeRedis()
        storage = RedisStorage(redis_client=client, prefix='custom:')
        storage.set('k', {'x': 1}, 60)
        assert 'custom:k' in client.data

    def test_missing(self):
        assert RedisStorage(redis_client=FakeRedis()).get('nope') is None

    def test_delete(self):
        client = FakeRedis()
        storage = RedisStorage(redis_client=client)
        storage.set('k', {'x': 1}, 60)
        storage.delete('k')
        assert storage.get('k') is None

    def test_requires_url_or_client(self):
        with pytest.raises(ValueError):
            RedisStorage()


class TestIncrement:
    def test_uses_eval_for_atomicity(self):
        client = FakeRedis(supports_eval=True)
        storage = RedisStorage(redis_client=client)
        assert storage.increment('rate:ip', 60) == 1
        assert storage.increment('rate:ip', 60) == 2
        assert client.eval_calls == 2
        # TTL ставится только при создании ключа и не продлевается
        assert client.ttl['kremle:rate:ip'] == 60

    def test_falls_back_to_pipeline(self):
        client = FakeRedis(supports_eval=False)
        storage = RedisStorage(redis_client=client)
        assert storage.increment('rate:ip', 60) == 1
        assert storage.increment('rate:ip', 60) == 2
        assert client.expire_calls == 1  # только при создании

    def test_get_counter_does_not_increment(self):
        client = FakeRedis()
        storage = RedisStorage(redis_client=client)
        storage.increment('rate:ip', 60)
        assert storage.get_counter('rate:ip') == 1
        assert storage.get_counter('rate:ip') == 1
        assert storage.get_counter('missing') == 0

    def test_get_counter_garbage(self):
        client = FakeRedis()
        client.data['kremle:bad'] = 'not-a-number'
        assert RedisStorage(redis_client=client).get_counter('bad') == 0


class TestLists:
    def test_blacklist(self):
        client = FakeRedis()
        storage = RedisStorage(redis_client=client)
        storage.blacklist_add('1.2.3.4', 60)
        assert storage.blacklist_check('1.2.3.4') is True
        assert storage.blacklist_list() == ['1.2.3.4']
        storage.blacklist_remove('1.2.3.4')
        assert storage.blacklist_check('1.2.3.4') is False

    def test_whitelist(self):
        storage = RedisStorage(redis_client=FakeRedis())
        storage.whitelist_add('10.0.0.1')
        assert storage.whitelist_check('10.0.0.1') is True
        assert storage.whitelist_list() == ['10.0.0.1']

    def test_events_ring(self):
        storage = RedisStorage(redis_client=FakeRedis())
        for i in range(5):
            storage.log_event({'ts': i, 'event': 'pass', 'ip': f'10.0.0.{i}'})
        events = storage.log_get(3)
        assert len(events) == 3
        assert events[0]['ip'] == '10.0.0.4'  # новые первыми

    def test_bad_event_json_skipped(self):
        client = FakeRedis()
        storage = RedisStorage(redis_client=client)
        client.data['kremle:events'] = ['not json', json.dumps({'event': 'pass'})]
        assert len(storage.log_get(10)) == 1


class TestMemoryCounter:
    def test_get_counter_missing(self):
        assert MemoryStorage().get_counter('nope') == 0

    def test_get_counter_after_increment(self):
        storage = MemoryStorage()
        storage.increment('rate:ip', 60)
        assert storage.get_counter('rate:ip') == 1
