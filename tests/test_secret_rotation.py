# -*- coding: utf-8 -*-
"""Секрет и его ротация (#29 роадмапа 2.10).

Две вещи, которых не было: предупреждение при старте с дефолтным ключом и
возможность сменить ключ, не обнулив все выданные челленджи.
"""

import logging

import pytest

from kremle_detect.captcha import DEFAULT_SECRET, CaptchaEngine

QUESTION = {'q': 'Сколько будет 2 + 2?', 'opts': ['4', '5', '6', '7'], 'ans': 0}


def make_engine(**kwargs):
    params = dict(
        secret='test-secret', storage=None, categories=['math'], question_count=1,
        max_errors=0, extra_questions=[dict(QUESTION)], only_extra=True,
    )
    params.update(kwargs)
    return CaptchaEngine(**params)


class TestDefaultSecret:
    def test_warning_on_default(self, caplog):
        with caplog.at_level(logging.WARNING, logger='kremle'):
            make_engine(secret=DEFAULT_SECRET)
        assert any('секрет по умолчанию' in record.message for record in caplog.records)

    def test_no_warning_on_own_secret(self, caplog):
        with caplog.at_level(logging.WARNING, logger='kremle'):
            make_engine(secret='мой-ключ')
        assert not any('секрет по умолчанию' in r.message for r in caplog.records)

    def test_default_secret_is_documented_constant(self):
        assert DEFAULT_SECRET == 'kremle-default-secret'

    def test_empty_secret_rejected(self):
        with pytest.raises(ValueError):
            make_engine(secret='')
        with pytest.raises(ValueError):
            make_engine(secret=[])


class TestRotation:
    def test_single_secret(self):
        engine = make_engine(secret='ключ')
        assert engine.secrets == ['ключ']
        assert engine.secret == 'ключ'

    def test_token_signed_with_old_key_still_valid(self):
        old = make_engine(secret='old-key')
        challenge = old.create_challenge()

        # ключ сменили, но старый оставили вторым — активная капча не рвётся
        rotated = make_engine(secret=['new-key', 'old-key'], storage=old.storage)
        assert rotated.get_challenge(challenge.token) is not None

    def test_token_signed_with_old_key_rejected_after_removal(self):
        old = make_engine(secret='old-key')
        challenge = old.create_challenge()

        strict = make_engine(secret=['new-key'], storage=old.storage)
        assert strict.get_challenge(challenge.token) is None

    def test_new_challenges_use_first_key(self):
        engine = make_engine(secret=['new-key', 'old-key'])
        challenge = engine.create_challenge()

        # новый токен подписан первым ключом: движок только со старым его не примет
        old_only = make_engine(secret=['old-key'], storage=engine.storage)
        assert old_only.get_challenge(challenge.token) is None
        assert engine.get_challenge(challenge.token) is not None

    def test_rotation_survives_verify(self):
        old = make_engine(secret='old-key')
        challenge = old.create_challenge()
        rotated = make_engine(secret=['new-key', 'old-key'], storage=old.storage)
        # варианты перемешиваются, поэтому правильные ответы берём у движка
        fresh = rotated.get_challenge(challenge.token)
        answers = {str(i): q['ans'] for i, q in enumerate(fresh.questions)}
        assert rotated.verify(challenge.token, answers)['passed'] is True

    def test_tampered_payload_rejected_with_any_key(self):
        old = make_engine(secret='old-key')
        challenge = old.create_challenge()
        # подменяем ответы в хранилище — HMAC не сойдётся ни одним ключом
        data = old.storage.get(f'challenge:{challenge.token}')
        # гарантированно другой вариант, чем настоящий ответ
        data['questions'][0]['ans'] = (data['questions'][0]['ans'] + 1) % len(
            data['questions'][0]['opts']
        )
        old.storage.set(f'challenge:{challenge.token}', data, 900)

        rotated = make_engine(secret=['new-key', 'old-key'], storage=old.storage)
        assert rotated.get_challenge(challenge.token) is None


class TestIntegrationSecrets:
    def test_flask_accepts_sequence(self):
        pytest.importorskip('flask')
        from flask import Flask

        from kremle_detect.integrations.flask_ext import KremleFlask

        app = Flask(__name__)
        kremle = KremleFlask(app, secret=['new-key', 'old-key'], categories=['math'])
        assert kremle.engine is not None
        assert kremle.engine.secrets == ['new-key', 'old-key']
        assert kremle.engine.secret == 'new-key'

    def test_fastapi_accepts_sequence(self):
        pytest.importorskip('fastapi')
        from fastapi import FastAPI

        from kremle_detect.integrations.fastapi_ext import KremleFastAPI

        app = FastAPI()
        kremle = KremleFastAPI(app, secret=['new-key', 'old-key'], categories=['math'])
        assert kremle.engine.secrets == ['new-key', 'old-key']
