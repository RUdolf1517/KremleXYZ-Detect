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
TOKEN_TTL = 900   # секунд — время жизни челленджа (15 минут)

# Rate limiting
DEFAULT_RATE_LIMIT = 10       # неудачных попыток
DEFAULT_RATE_WINDOW = 600     # за 10 минут
DEFAULT_CHALLENGE_RATE_LIMIT = 60  # выдач челленджа с одного IP за окно


def _require_int(name: str, value: Any, minimum: int) -> int:
    """Валидация числовой настройки на старте — лучше упасть сразу, чем в бою."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f'{name} должен быть целым числом, получено {type(value).__name__}')
    if value < minimum:
        raise ValueError(f'{name} должен быть >= {minimum}, получено {value}')
    return value


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

    def to_dict(self, verify_url: str = '/kremle/verify') -> dict:
        """Данные для отправки клиенту."""
        return {
            'questions': self.safe_questions,
            'token': self.token,
            'created_at': self.created_at,
            'verify_url': verify_url,
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
        challenge_rate_limit: int = DEFAULT_CHALLENGE_RATE_LIMIT,
        on_detect: Optional[Callable] = None,
        on_pass: Optional[Callable] = None,
        on_fail: Optional[Callable] = None,
        fail_threshold: int = 0,
        blacklist_ttl: int = 86400,
    ):
        """
        Args:
            categories: категории встроенных вопросов.
            question_count: сколько вопросов в одном челлендже.
            max_errors: допустимое число ошибок (строго меньше question_count).
            secret: секрет для HMAC-подписи токенов.
            extra_questions: список своих вопросов.
            only_extra: если True — только extra_questions.
            storage: бэкенд хранения (MemoryStorage/RedisStorage).
                     None → MemoryStorage.
            rate_limit: макс. число НЕУДАЧНЫХ проверок с одного IP за rate_window.
                        Успешное прохождение сбрасывает счётчик. 0 — отключить.
            rate_window: окно rate limit в секундах.
            challenge_rate_limit: макс. выдач челленджа с одного IP за окно
                        (защита от забивания хранилища). 0 — отключить.
            on_detect: callback(detect_result, ip) — вызывается при детекции.
            on_pass: callback(ip, errors, total) — вызывается при прохождении капчи.
            on_fail: callback(ip, errors, total) — вызывается при провале капчи.
        """
        self.categories = list(categories) if categories else list(ALL_CATEGORY_NAMES)
        self.question_count = _require_int('question_count', question_count, 1)
        self.max_errors = _require_int('max_errors', max_errors, 0)
        if self.max_errors >= self.question_count:
            # Не роняем приложение из-за настройки: подрезаем до безопасного
            # значения (на 1 вопрос всегда должен быть хотя бы 1 верный ответ)
            # и громко объясняем в лог.
            logger.warning(
                'max_errors=%d >= question_count=%d: капча проходилась бы без '
                'правильных ответов. Значение уменьшено до %d.',
                self.max_errors, self.question_count, self.question_count - 1,
            )
            self.max_errors = self.question_count - 1
        self.secret = secret
        self.extra_questions = list(extra_questions) if extra_questions else []
        if self.extra_questions:
            validate_questions(self.extra_questions)
        self.only_extra = only_extra
        self.storage = storage or MemoryStorage()
        self.rate_limit = _require_int('rate_limit', rate_limit, 0)
        self.rate_window = _require_int('rate_window', rate_window, 1)
        self.challenge_rate_limit = _require_int(
            'challenge_rate_limit', challenge_rate_limit, 0
        )
        self._rng = random.SystemRandom()
        self._warned_small_pool = False

        # Callbacks
        self.on_detect = on_detect
        self.on_pass = on_pass
        self.on_fail = on_fail

        # Blacklist: авто-бан после N провалов подряд
        # fail_threshold=0 — отключить, blacklist_ttl=0 — навсегда
        self.fail_threshold = _require_int('fail_threshold', fail_threshold, 0)
        self.blacklist_ttl = _require_int('blacklist_ttl', blacklist_ttl, 0)

    def create_challenge(self) -> Challenge:
        """Создаёт новый набор вопросов."""
        if self.only_extra:
            if not self.extra_questions:
                raise ValueError(
                    'only_extra=True но extra_questions пуст — нечего показывать'
                )
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

        self._rng.shuffle(pool)
        questions = pool[:self.question_count]

        # Пул может оказаться меньше question_count (мало категорий/своих вопросов).
        # Проверка реального числа вопросов — в verify(): лимит ошибок там
        # подрезается до len(questions) - 1. Здесь только предупреждаем.
        if len(questions) <= self.max_errors and not self._warned_small_pool:
            self._warned_small_pool = True
            logger.warning(
                'В пуле %d вопрос(ов), а max_errors=%d — лимит ошибок будет '
                'уменьшен до %d. Добавьте категории/свои вопросы или уменьшите '
                'max_errors.',
                len(questions), self.max_errors, max(len(questions) - 1, 0),
            )

        # Перемешиваем варианты ответов на сервере: индекс правильного ответа
        # меняется от челленджа к челленджу (боты не могут всегда отправлять 0).
        for q in questions:
            correct_text = q['opts'][q['ans']]
            shuffled = q['opts'][:]
            self._rng.shuffle(shuffled)
            q['opts'] = shuffled
            q['ans'] = shuffled.index(correct_text)

        challenge = Challenge(questions, self.secret)

        self.storage.set(
            f'challenge:{challenge.token}',
            challenge._serialize(),
            TOKEN_TTL,
        )

        logger.info('Challenge created: token=%s questions=%d', challenge.token[:16], len(questions))
        return challenge

    def get_challenge(self, token: str) -> Optional[Challenge]:
        """Получить челлендж по токену с проверкой HMAC (защита от подмены в хранилище)."""
        data = self.storage.get(f'challenge:{token}')
        if data is None:
            return None
        # Re-derive the expected token from stored data and compare.
        # If Redis/memory was tampered with (e.g. answers changed), this fails.
        answers_str = json.dumps([q['ans'] for q in data['questions']], separators=(',', ':'))
        expected = _sign(f'{answers_str}:{data["created_at"]}', self.secret)
        if not hmac.compare_digest(expected, token):
            logger.warning('Challenge HMAC mismatch — possible storage tampering: token=%s', token[:16])
            return None
        return Challenge._deserialize(data)

    def check_rate_limit(self, ip: str) -> bool:
        """
        True если IP уже исчерпал лимит НЕУДАЧНЫХ проверок.

        Метод только читает счётчик: успешные прохождения не расходуют лимит
        и не могут заблокировать честного пользователя.
        """
        if self.rate_limit <= 0 or not ip:
            return False
        if self.storage.get_counter(f'rate:{ip}') >= self.rate_limit:
            logger.warning('Rate limit exceeded: ip=%s limit=%d', ip, self.rate_limit)
            return True
        return False

    def _track_rate_attempt(self, ip: str) -> None:
        """Учесть неудачную проверку в счётчике rate limit."""
        if self.rate_limit <= 0 or not ip:
            return
        self.storage.increment(f'rate:{ip}', self.rate_window)

    def _clear_rate_attempts(self, ip: str) -> None:
        """Сбросить счётчик после успешного прохождения."""
        if ip:
            self.storage.delete(f'rate:{ip}')

    # ── Лимит выдачи челленджей ──────────────────────────────────────────────

    def check_challenge_limit(self, ip: str) -> bool:
        """True если IP превысил лимит запросов новых челленджей."""
        if self.challenge_rate_limit <= 0 or not ip:
            return False
        return self.storage.get_counter(f'chrate:{ip}') >= self.challenge_rate_limit

    def track_challenge(self, ip: str) -> None:
        """Учесть выдачу челленджа (для защиты хранилища от забивания)."""
        if self.challenge_rate_limit <= 0 or not ip:
            return
        self.storage.increment(f'chrate:{ip}', self.rate_window)

    # ── Whitelist API ────────────────────────────────────────────────────────

    def whitelist_add(self, ip: str) -> None:
        """Добавить IP в белый список (persistent, через storage)."""
        self.storage.whitelist_add(ip)
        logger.info('IP whitelisted: ip=%s', ip)

    def whitelist_remove(self, ip: str) -> None:
        """Убрать IP из белого списка."""
        self.storage.whitelist_remove(ip)
        logger.info('IP removed from whitelist: ip=%s', ip)

    def is_whitelisted(self, ip: str) -> bool:
        """Проверить, в белом ли списке IP."""
        return self.storage.whitelist_check(ip)

    # ── Blacklist API ────────────────────────────────────────────────────────

    def blacklist_add(self, ip: str, ttl: Optional[int] = None) -> None:
        """
        Вручную добавить IP в чёрный список.

        Args:
            ip: IP-адрес
            ttl: время бана в секундах (None = использовать blacklist_ttl, 0 = навсегда)
        """
        _ttl = self.blacklist_ttl if ttl is None else ttl
        self.storage.blacklist_add(ip, _ttl)
        logger.warning('IP blacklisted: ip=%s ttl=%d', ip, _ttl)

    def blacklist_remove(self, ip: str) -> None:
        """Убрать IP из чёрного списка."""
        self.storage.blacklist_remove(ip)
        logger.info('IP removed from blacklist: ip=%s', ip)

    def is_blacklisted(self, ip: str) -> bool:
        """Проверить, в чёрном ли списке IP."""
        return self.storage.blacklist_check(ip)

    def _track_fail(self, ip: str) -> None:
        """Счётчик провалов. Бан при достижении fail_threshold."""
        if self.fail_threshold <= 0 or not ip:
            return
        # TTL для счётчика провалов — отдельное окно, не rate_window.
        # Используем blacklist_ttl как верхнюю границу: если не набрал threshold
        # за это время — счётчик сбрасывается сам. blacklist_ttl=0 («навсегда»)
        # нельзя передавать в TTL счётчика: он истечёт мгновенно и авто-бан
        # не сработает никогда.
        ttl = self.blacklist_ttl if self.blacklist_ttl > 0 else 86400 * 365 * 10
        count = self.storage.increment(f'fails:{ip}', ttl)
        if count >= self.fail_threshold:
            self.blacklist_add(ip)
            self.storage.delete(f'fails:{ip}')
            logger.warning('Auto-blacklisted after %d fails: ip=%s', count, ip)

    def _track_pass(self, ip: str) -> None:
        """Сбросить счётчик провалов при успехе."""
        if ip:
            self.storage.delete(f'fails:{ip}')

    def verify(
        self,
        token: str,
        answers: Dict[str, Any],
        ip: Optional[str] = None,
        fingerprint: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Проверяет ответы пользователя.

        Args:
            token: токен челленджа
            answers: { "0": 2, "1": 0, ... } — индекс вопроса → индекс варианта
            ip: IP пользователя (для rate limiting, blacklist и логов)
            fingerprint: JS-фингерпринт от клиента (honeypot, userAgentData и т.д.)

        Returns:
            { 'passed': bool, 'errors': int, 'total': int }
            при блокировке дополнительно 'error': 'invalid_token' | 'rate_limited'
            | 'blacklisted' | 'invalid_answers'.

        Токен одноразовый: он удаляется после любой проверки (успешной или нет),
        поэтому для повтора клиент должен запросить новый челлендж.
        """
        # Fingerprint — ужесточаем порог, но не блокируем наглухо.
        # Яндекс Браузер автозаполняет скрытые поля (honeypot), поэтому
        # honeypot тоже не может быть hard-block — иначе живые люди не пройдут.
        if not isinstance(answers, dict):
            return {'passed': False, 'errors': -1, 'total': 0, 'error': 'invalid_answers'}
        if fingerprint is not None and not isinstance(fingerprint, dict):
            fingerprint = None

        effective_max_errors = self.max_errors
        if fingerprint:
            strong_ya = (
                fingerprint.get('yaBrands')
                or fingerprint.get('yandexApi')
                or fingerprint.get('honeypot')
            )
            if strong_ya:
                effective_max_errors = 0  # требуем идеальный результат
                logger.info('Fingerprint strict mode (signals: yaBrands=%s yandexApi=%s honeypot=%s): ip=%s',
                            fingerprint.get('yaBrands'), fingerprint.get('yandexApi'),
                            fingerprint.get('honeypot'), ip)

        # Blacklist
        if ip and self.is_blacklisted(ip):
            logger.warning('Verify blocked by blacklist: ip=%s', ip)
            self.storage.log_event({'ts': time.time(), 'event': 'blocked', 'ip': ip, 'reason': 'blacklisted'})
            return {'passed': False, 'errors': -1, 'total': 0, 'error': 'blacklisted'}

        # Rate limiting
        if ip and self.check_rate_limit(ip):
            logger.warning('Verify blocked by rate limit: ip=%s', ip)
            self.storage.log_event({'ts': time.time(), 'event': 'blocked', 'ip': ip, 'reason': 'rate_limited'})
            return {'passed': False, 'errors': -1, 'total': 0, 'error': 'rate_limited'}

        challenge = self.get_challenge(token)
        if challenge is None:
            logger.debug('Invalid token: %s', token[:16] if token else 'empty')
            return {'passed': False, 'errors': -1, 'total': 0, 'error': 'invalid_token'}

        errors = 0
        for i, q in enumerate(challenge.questions):
            chosen = answers.get(str(i))
            # Client sends the index of the chosen option (0-based in shuffled opts).
            # Server stores q['ans'] as the correct shuffled index after create_challenge().
            try:
                if chosen is None or int(chosen) != q['ans']:
                    errors += 1
            except (TypeError, ValueError):
                errors += 1

        total = len(challenge.questions)
        # На 1 вопрос — минимум 1 верный ответ: даже если пул оказался меньше
        # question_count, свободного прохода не будет.
        effective_max_errors = min(effective_max_errors, max(total - 1, 0))

        passed = errors <= effective_max_errors

        # Токен одноразовый: после любой проверки он сгорает, повтор требует
        # нового челленджа (иначе один токен = бесконечные попытки угадать).
        self.storage.delete(f'challenge:{token}')
        if passed:
            self._clear_rate_attempts(ip)
            self._track_pass(ip)
            logger.info('Captcha PASSED: ip=%s errors=%d/%d', ip, errors, total)
            self.storage.log_event({
                'ts': time.time(), 'event': 'pass',
                'ip': ip, 'errors': errors, 'total': total,
            })
            if self.on_pass:
                self.on_pass(ip, errors, total)
        else:
            self._track_rate_attempt(ip)
            self._track_fail(ip)
            logger.info('Captcha FAILED: ip=%s errors=%d/%d', ip, errors, total)
            self.storage.log_event({
                'ts': time.time(), 'event': 'fail',
                'ip': ip, 'errors': errors, 'total': total,
            })
            if self.on_fail:
                self.on_fail(ip, errors, total)

        return {
            'passed': passed,
            'errors': errors,
            'total': total,
        }

    def notify_detect(self, detect_result, ip: str = None) -> None:
        """Вызвать callback при детекции (используется интеграциями)."""
        logger.info('Yandex detected: ip=%s reason=%s', ip, detect_result.reason)
        self.storage.log_event({
            'ts': time.time(), 'event': 'detect',
            'ip': ip, 'reason': detect_result.reason,
        })
        if self.on_detect:
            self.on_detect(detect_result, ip)
