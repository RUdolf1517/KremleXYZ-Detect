# -*- coding: utf-8 -*-
"""
Ядро капчи — фреймворк-агностичная логика.

Создаёт «челлендж» (набор вопросов) и проверяет ответы.
Не зависит от Flask/Django/FastAPI.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import random
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

from .questions import get_questions, validate_questions, ALL_CATEGORY_NAMES
from .storage import BaseStorage, MemoryStorage

logger = logging.getLogger('kremle')

DEFAULT_QUESTION_COUNT = 15
DEFAULT_MAX_ERRORS = 3
TOKEN_TTL = 3600  # секунд — время жизни челленджа

# Rate limiting
DEFAULT_RATE_LIMIT = 10       # попыток
DEFAULT_RATE_WINDOW = 600     # за 10 минут


def _sign(data: str, secret: str) -> str:
    return hmac.new(secret.encode(), data.encode(), hashlib.sha256).hexdigest()


class Challenge:
    """
    Один набор вопросов для прохождения капчи.

    Attributes:
        questions: полный список вопросов (с ответами) — хранится на сервере
        safe_questions: список без ответов — отдаётся клиенту
        token: подпись для верификации
        created_at: timestamp создания
    """

    def __init__(
        self,
        questions: List[dict],
        secret: str = 'kremle-default-secret',
    ):
        self.questions = questions
        self.created_at = time.time()

        # Токен = HMAC от ответов + timestamp (защита от подделки)
        answers_str = json.dumps([q['ans'] for q in questions], separators=(',', ':'))
        self.token = _sign(f'{answers_str}:{self.created_at}', secret)

        # Безопасная версия — без правильных ответов
        self.safe_questions = []
        for q in questions:
            safe = {'q': q['q'], 'opts': q['opts']}
            if 'category' in q:
                safe['category'] = q['category']
            self.safe_questions.append(safe)

    def to_dict(self) -> dict:
        """Данные для отправки клиенту."""
        return {
            'questions': self.safe_questions,
            'token': self.token,
            'created_at': self.created_at,
        }

    def _serialize(self) -> dict:
        """Сериализация для хранения в storage."""
        return {
            'questions': self.questions,
            'safe_questions': self.safe_questions,
            'token': self.token,
            'created_at': self.created_at,
        }

    @classmethod
    def _deserialize(cls, data: dict) -> 'Challenge':
        """Восстановление из storage."""
        obj = object.__new__(cls)
        obj.questions = data['questions']
        obj.safe_questions = data['safe_questions']
        obj.token = data['token']
        obj.created_at = data['created_at']
        return obj


class CaptchaEngine:
    """
    Главный класс — создаёт челленджи и проверяет ответы.

    Пример использования:
        engine = CaptchaEngine(
            categories=['math', 'physics'],
            question_count=10,
            max_errors=2,
            secret='my-secret-key',
        )

        # Создать челлендж
        challenge = engine.create_challenge()

        # Отдать клиенту
        data = challenge.to_dict()

        # Проверить ответы
        result = engine.verify(challenge.token, user_answers={'0': 0, '1': 2, ...})
    """

    def __init__(
        self,
        categories: Optional[Sequence[str]] = None,
        question_count: int = DEFAULT_QUESTION_COUNT,
        max_errors: int = DEFAULT_MAX_ERRORS,
        secret: str = 'kremle-default-secret',
        extra_questions: Optional[List[dict]] = None,
        only_extra: bool = False,
        storage: Optional[BaseStorage] = None,
        rate_limit: int = DEFAULT_RATE_LIMIT,
        rate_window: int = DEFAULT_RATE_WINDOW,
        on_detect: Optional[Callable] = None,
        on_pass: Optional[Callable] = None,
        on_fail: Optional[Callable] = None,
    ):
        """
        Args:
            categories: категории встроенных вопросов.
            question_count: сколько вопросов в одном челлендже.
            max_errors: допустимое число ошибок.
            secret: секрет для HMAC-подписи токенов.
            extra_questions: список своих вопросов.
            only_extra: если True — только extra_questions.
            storage: бэкенд хранения (MemoryStorage/RedisStorage).
                     None → MemoryStorage.
            rate_limit: макс. попыток верификации с одного IP за rate_window.
                        0 — отключить.
            rate_window: окно rate limit в секундах.
            on_detect: callback(detect_result, ip) — вызывается при детекции.
            on_pass: callback(ip, errors, total) — вызывается при прохождении капчи.
            on_fail: callback(ip, errors, total) — вызывается при провале капчи.
        """
        self.categories = list(categories) if categories else list(ALL_CATEGORY_NAMES)
        self.question_count = question_count
        self.max_errors = max_errors
        self.secret = secret
        self.extra_questions = list(extra_questions) if extra_questions else []
        if self.extra_questions:
            validate_questions(self.extra_questions)
        self.only_extra = only_extra
        self.storage = storage or MemoryStorage()
        self.rate_limit = rate_limit
        self.rate_window = rate_window

        # Callbacks
        self.on_detect = on_detect
        self.on_pass = on_pass
        self.on_fail = on_fail

    def create_challenge(self) -> Challenge:
        """Создаёт новый набор вопросов."""
        if self.only_extra:
            pool = [dict(q) for q in self.extra_questions]
        else:
            pool = get_questions(
                categories=self.categories,
                count=None,
                shuffle=False,
            )
            for q in self.extra_questions:
                entry = dict(q)
                entry.setdefault('category', 'custom')
                pool.append(entry)

        random.shuffle(pool)
        questions = pool[:self.question_count]
        challenge = Challenge(questions, self.secret)

        self.storage.set(
            f'challenge:{challenge.token}',
            challenge._serialize(),
            TOKEN_TTL,
        )

        logger.info('Challenge created: token=%s questions=%d', challenge.token[:16], len(questions))
        return challenge

    def get_challenge(self, token: str) -> Optional[Challenge]:
        """Получить челлендж по токену."""
        data = self.storage.get(f'challenge:{token}')
        if data is None:
            return None
        return Challenge._deserialize(data)

    def check_rate_limit(self, ip: str) -> bool:
        """
        Проверяет rate limit для IP. Возвращает True если лимит превышен.
        """
        if self.rate_limit <= 0:
            return False
        count = self.storage.increment(f'rate:{ip}', self.rate_window)
        if count > self.rate_limit:
            logger.warning('Rate limit exceeded: ip=%s count=%d', ip, count)
            return True
        return False

    def verify(
        self,
        token: str,
        answers: Dict[str, Any],
        ip: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Проверяет ответы пользователя.

        Args:
            token: токен челленджа
            answers: { "0": 2, "1": 0, ... } — индекс вопроса → индекс варианта
            ip: IP пользователя (для rate limiting и логов)

        Returns:
            { 'passed': bool, 'errors': int, 'total': int }
        """
        # Rate limiting
        if ip and self.check_rate_limit(ip):
            logger.warning('Verify blocked by rate limit: ip=%s', ip)
            return {
                'passed': False,
                'errors': -1,
                'total': 0,
                'error': 'rate_limited',
            }

        challenge = self.get_challenge(token)
        if challenge is None:
            logger.debug('Invalid token: %s', token[:16] if token else 'empty')
            return {'passed': False, 'errors': -1, 'total': 0, 'error': 'invalid_token'}

        errors = 0
        for i, q in enumerate(challenge.questions):
            chosen = answers.get(str(i))
            if chosen is None or int(chosen) != q['ans']:
                errors += 1

        passed = errors <= self.max_errors

        if passed:
            self.storage.delete(f'challenge:{token}')
            logger.info('Captcha PASSED: ip=%s errors=%d/%d', ip, errors, len(challenge.questions))
            if self.on_pass:
                self.on_pass(ip, errors, len(challenge.questions))
        else:
            logger.info('Captcha FAILED: ip=%s errors=%d/%d', ip, errors, len(challenge.questions))
            if self.on_fail:
                self.on_fail(ip, errors, len(challenge.questions))

        return {
            'passed': passed,
            'errors': errors,
            'total': len(challenge.questions),
        }

    def notify_detect(self, detect_result, ip: str = None) -> None:
        """Вызвать callback при детекции (используется интеграциями)."""
        logger.info('Yandex detected: ip=%s reason=%s', ip, detect_result.reason)
        if self.on_detect:
            self.on_detect(detect_result, ip)
