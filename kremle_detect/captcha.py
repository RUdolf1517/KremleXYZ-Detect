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
import time
from typing import Any, Dict, List, Optional, Sequence

from .questions import get_questions, validate_questions, ALL_CATEGORY_NAMES

DEFAULT_QUESTION_COUNT = 15
DEFAULT_MAX_ERRORS = 3
TOKEN_TTL = 3600  # секунд — время жизни челленджа


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
        result = engine.verify(challenge, user_answers={'0': 0, '1': 2, ...})
    """

    def __init__(
        self,
        categories: Optional[Sequence[str]] = None,
        question_count: int = DEFAULT_QUESTION_COUNT,
        max_errors: int = DEFAULT_MAX_ERRORS,
        secret: str = 'kremle-default-secret',
        extra_questions: Optional[List[dict]] = None,
        only_extra: bool = False,
    ):
        """
        Args:
            categories: категории встроенных вопросов.
            question_count: сколько вопросов в одном челлендже.
            max_errors: допустимое число ошибок.
            secret: секрет для HMAC-подписи токенов.
            extra_questions: список своих вопросов в формате:
                [{"q": "Вопрос?", "opts": ["А", "Б", "В"], "ans": 0}, ...]
                ans — индекс правильного варианта в opts.
            only_extra: если True — использовать только extra_questions,
                        встроенные категории игнорируются.
        """
        self.categories = list(categories) if categories else list(ALL_CATEGORY_NAMES)
        self.question_count = question_count
        self.max_errors = max_errors
        self.secret = secret
        self.extra_questions = list(extra_questions) if extra_questions else []
        if self.extra_questions:
            validate_questions(self.extra_questions)
        self.only_extra = only_extra

        # Хранилище активных челленджей (token → Challenge)
        self._challenges: Dict[str, Challenge] = {}

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

        import random
        random.shuffle(pool)
        questions = pool[:self.question_count]
        challenge = Challenge(questions, self.secret)
        self._challenges[challenge.token] = challenge
        self._cleanup_expired()
        return challenge

    def get_challenge(self, token: str) -> Optional[Challenge]:
        """Получить челлендж по токену."""
        ch = self._challenges.get(token)
        if ch and (time.time() - ch.created_at) > TOKEN_TTL:
            del self._challenges[token]
            return None
        return ch

    def verify(
        self,
        token: str,
        answers: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Проверяет ответы пользователя.

        Args:
            token: токен челленджа
            answers: { "0": 2, "1": 0, ... } — индекс вопроса → индекс варианта

        Returns:
            { 'passed': bool, 'errors': int, 'total': int }
        """
        challenge = self.get_challenge(token)
        if challenge is None:
            return {'passed': False, 'errors': -1, 'total': 0, 'error': 'invalid_token'}

        errors = 0
        for i, q in enumerate(challenge.questions):
            chosen = answers.get(str(i))
            if chosen is None or int(chosen) != q['ans']:
                errors += 1

        passed = errors <= self.max_errors

        if passed:
            # Удаляем использованный челлендж
            self._challenges.pop(token, None)

        return {
            'passed': passed,
            'errors': errors,
            'total': len(challenge.questions),
        }

    def _cleanup_expired(self) -> None:
        """Удаляет просроченные челленджи."""
        now = time.time()
        expired = [t for t, c in self._challenges.items() if (now - c.created_at) > TOKEN_TTL]
        for t in expired:
            del self._challenges[t]
