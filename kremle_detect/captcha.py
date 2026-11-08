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

from .images import DEFAULT_PREFIX as DEFAULT_IMAGES_PREFIX, rewrite_questions as _rewrite_images
from .metrics import Metrics
from .telemetry import span
from .policy import (
    ALLOW, CHALLENGE, MONITOR, Decision, normalize_policy, reasons_from_hits,
    validate_sample_rate,
)
from .questions import (
    ALL_CATEGORY_NAMES, DEFAULT_MIXED_RATIO, DEFAULT_STALE_CACHE_HOURS,
    MIXED_SOURCE, attribution_text, get_questions, mix_questions,
    normalize_source, question_sources, questions_health, validate_mixed_ratio,
    validate_questions,
)
from .storage import BaseStorage, MemoryStorage

logger = logging.getLogger('kremle')

DEFAULT_QUESTION_COUNT = 15
DEFAULT_MAX_ERRORS = 3
TOKEN_TTL = 900   # секунд — время жизни челленджа (15 минут)

# Rate limiting
DEFAULT_RATE_LIMIT = 10       # неудачных попыток
DEFAULT_RATE_WINDOW = 600     # за 10 минут
DEFAULT_CHALLENGE_RATE_LIMIT = 60  # выдач челленджа с одного IP за окно

#: Ротация: сколько последних показанных вопросов помнить, чтобы не повторять
#: их в следующих челленджах (вопросов в банке может быть всего 15).
RECENT_QUESTIONS_LIMIT = 400
RECENT_QUESTIONS_TTL = 6 * 3600

#: Сколько живёт серия провалов с одного IP. «Подряд» — это не «за месяц»:
#: человек, вернувшийся через час, снова видит обычную капчу.
ADAPTIVE_STREAK_TTL = 30 * 60

#: Максимум ступеней ужесточения. Дальше растут только счётчик rate limit и
#: блоклист: бесконечно длинная капча просто перестаёт быть проходимой.
ADAPTIVE_MAX_LEVEL = 3


def _question_key(question: dict) -> str:
    """
    Ключ вопроса для дедупликации и ротации — нормализованный текст.

    Варианты ответа не годятся: один и тот же вопрос может прийти с другим
    порядком ``opts`` (и приходит — их перемешивает сервер).
    """
    text = question.get('q') or ''
    return ' '.join(str(text).split()).lower()


def _dedupe_questions(questions: List[dict]) -> List[dict]:
    """Убрать повторы по тексту: отвечать одно и то же дважды бессмысленно."""
    seen = set()
    result: List[dict] = []
    for question in questions:
        key = _question_key(question)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(question)
    return result


def _require_int(name: str, value: Any, minimum: int) -> int:
    """Валидация числовой настройки на старте — лучше упасть сразу, чем в бою."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f'{name} должен быть целым числом, получено {type(value).__name__}')
    if value < minimum:
        raise ValueError(f'{name} должен быть >= {minimum}, получено {value}')
    return value


DEFAULT_SECRET = 'kremle-default-secret'


def _sign(data: str, secret: str) -> str:
    return hmac.new(secret.encode(), data.encode(), hashlib.sha256).hexdigest()


def _normalize_secrets(secret: Any, logger_: logging.Logger = logger) -> List[str]:
    """
    Привести ``secret`` к списку ключей: первый подписывает, все проверяют.

    Список нужен для плавной ротации: какое-то время живут челленджи,
    подписанные старым ключом, и если его сразу выбросить — все, кто в середине
    капчи, получат ``invalid_token``.

    Пример:
        _normalize_secrets('new')            # ['new']
        _normalize_secrets(['new', 'old'])    # ['new', 'old']
    """
    if isinstance(secret, str):
        secrets = [secret] if secret else []
    else:
        secrets = [str(item) for item in secret if str(item)]
    if not secrets:
        raise ValueError('secret не может быть пустым')
    if secrets[0] == DEFAULT_SECRET:
        logger_.warning(
            'Используется секрет по умолчанию (%r): токены капчи может подделать '
            'любой, кто знает этот ключ. Задайте свой: secret="..." или '
            'KREMLE_SECRET.', DEFAULT_SECRET,
        )
    return secrets


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
        secret: str = DEFAULT_SECRET,
        max_errors: Optional[int] = None,
    ):
        self.questions = questions
        self.created_at = time.time()
        # Порог, по которому выдан именно этот челлендж. None — «как настроено
        # в движке». Адаптивная сложность меняет порог на лету, и проверять
        # ответы по текущим настройкам было бы нечестно: строгий челлендж
        # оценивался бы по мягкому порогу.
        self.max_errors = max_errors

        # Токен = HMAC от ответов + timestamp (защита от подделки)
        answers_str = json.dumps([q['ans'] for q in questions], separators=(',', ':'))
        self.token = _sign(f'{answers_str}:{self.created_at}', secret)

        # Безопасная версия — без правильных ответов
        self.safe_questions = []
        for q in questions:
            safe = {'q': q['q'], 'opts': q['opts']}
            if 'category' in q:
                safe['category'] = q['category']
            if 'source' in q:
                safe['source'] = q['source']
            if 'source_kind' in q:
                safe['source_kind'] = q['source_kind']
            if 'problem_id' in q:
                safe['problem_id'] = q['problem_id']
            if q.get('images'):
                safe['images'] = []
                for img in q['images'][:3]:
                    if not isinstance(img, dict) or not img.get('url'):
                        continue
                    item = {'url': img['url'], 'alt': img.get('alt', '')}
                    if img.get('remote_url'):
                        # исходный адрес: рисунок из кеша отдаётся локально,
                        # но для отладки полезно видеть, откуда он пришёл
                        item['remote_url'] = img['remote_url']
                    safe['images'].append(item)
            self.safe_questions.append(safe)

    def to_dict(
        self,
        verify_url: str = '/kremle/verify',
        max_errors: Optional[int] = None,
        ttl: int = TOKEN_TTL,
    ) -> dict:
        """
        Данные для отправки клиенту (+ атрибуция источников вопросов).

        Args:
            verify_url: адрес проверки ответов.
            max_errors: сколько ошибок допустимо — клиент должен показывать
                правду, а не угадывать порог (``errors > total / 2``).
            ttl: срок жизни челленджа в секундах; клиент получает
                ``expires_in`` и может показать таймер.
        """
        remaining = max(0, int(ttl - (time.time() - self.created_at)))
        data = {
            'questions': self.safe_questions,
            'token': self.token,
            'created_at': self.created_at,
            'verify_url': verify_url,
            'expires_in': remaining,
            'sources': question_sources(self.questions),
            'attribution': attribution_text(self.questions),
        }
        if max_errors is not None:
            data['max_errors'] = max_errors
        return data

    def _serialize(self) -> dict:
        """Сериализация для хранения в storage."""
        return {
            'questions': self.questions,
            'safe_questions': self.safe_questions,
            'token': self.token,
            'created_at': self.created_at,
            'max_errors': self.max_errors,
        }

    @classmethod
    def _deserialize(cls, data: dict) -> Challenge:
        """Восстановление из storage."""
        obj = object.__new__(cls)
        obj.questions = data['questions']
        obj.safe_questions = data['safe_questions']
        obj.token = data['token']
        obj.created_at = data['created_at']
        # челленджи, выданные до 2.12, поля не имеют — это не повод падать
        obj.max_errors = data.get('max_errors')
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
        data = challenge.to_dict(max_errors=engine.max_errors)

        # Проверить ответы
        result = engine.verify(challenge.token, user_answers={'0': 0, '1': 2, ...})
    """

    def __init__(
        self,
        categories: Optional[Sequence[str]] = None,
        question_count: int = DEFAULT_QUESTION_COUNT,
        max_errors: int = DEFAULT_MAX_ERRORS,
        secret: str | Sequence[str] = DEFAULT_SECRET,
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
        policy: Optional[Dict[str, str]] = None,
        sample_rate: float = 1.0,
        metrics_enabled: bool = True,
        verified_ttl: int = 86400,
        bind_ip: bool = False,
        bind_ua: bool = False,
        questions_source: str = 'auto',
        mixed_ratio: float = DEFAULT_MIXED_RATIO,
        adaptive: bool = True,
        adaptive_threshold: int = 3,
        adaptive_extra_questions: int = 2,
        questions_images: bool = False,
        images_cache_dir: Optional[str] = None,
        images_prefix: str = DEFAULT_IMAGES_PREFIX,
    ):
        """
        Args:
            categories: категории встроенных вопросов.
            question_count: сколько вопросов в одном челлендже.
            max_errors: допустимое число ошибок (строго меньше question_count).
            secret: секрет для HMAC-подписи токенов — строка или список строк.
                Первый ключ подписывает новые челленджи, остальные принимаются
                при проверке: так ключ меняют без того, чтобы разом убить все
                выданные капчи (``secret=['новый', 'старый']``). Пустой секрет
                по умолчанию вызывает ``WARNING``.
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
            policy: действия по сегментам, например
                ``{'yandex_bot': 'block', 'yandex_referrer': 'monitor'}``.
                Действия: ``challenge`` (по умолчанию), ``block``, ``monitor``,
                ``allow``.
            sample_rate: доля детектированных запросов, которым реально
                показывается капча (0..1). Остальные уходят в shadow-статистику.
            metrics_enabled: вести счётчики в хранилище.
            verified_ttl: сколько секунд действует «капча пройдена» (0 — бессрочно).
            bind_ip: переспрашивать капчу при смене IP.
            bind_ua: переспрашивать капчу при смене User-Agent.
            adaptive: ужесточать капчу после серии провалов с одного IP
                (по умолчанию да). Первый провал ничего не меняет.
            adaptive_threshold: сколько провалов подряд включают следующую
                ступень (по умолчанию 3).
            adaptive_extra_questions: сколько вопросов добавлять на каждой
                ступени (по умолчанию 2); порог ошибок уменьшается на столько
                же, но не ниже нуля.
            questions_images: показывать задания с рисунком (по умолчанию нет)
            images_cache_dir: каталог локального кеша картинок (по умолчанию
                ``~/.cache/kremle-detect/images``, см. ``kremle_detect.images``).
                Если картинка уже скачана, клиент получает ссылку на свой роут
                ``/kremle/img/<key>`` вместо портала; иначе — горячую ссылку.
            images_prefix: префикс URL для картинок из кеша.
            questions_source: откуда брать вопросы: ``auto`` (кеш РешуЕГЭ, если
                есть, иначе встроенный банк), ``own`` (только свой банк;
                ``builtin`` — алиас), ``sdamgia`` (только кеш портала),
                ``own+sdamgia`` (оба источника в одной капче).
            mixed_ratio: доля вопросов «Решу ЕГЭ» для ``own+sdamgia`` (0..1,
                по умолчанию 0.5); остальными режимами игнорируется.
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
        #: Все действующие ключи: первый подписывает новые челленджи,
        #: остальные принимаются при проверке (плавная ротация).
        self.secrets = _normalize_secrets(secret)
        self.secret = self.secrets[0]
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

        # Политика сегментов и метрики
        self.policy = normalize_policy(policy)
        self.sample_rate = validate_sample_rate(sample_rate)
        self.metrics = Metrics(self.storage, enabled=metrics_enabled)

        # Срок жизни «пройдено» и привязка к клиенту
        self.verified_ttl = _require_int('verified_ttl', verified_ttl, 0)
        self.bind_ip = bool(bind_ip)
        self.bind_ua = bool(bind_ua)

        # старые имена (builtin/auto) остаются рабочими до 3.0
        self.questions_source = normalize_source(questions_source)
        self.mixed_ratio = validate_mixed_ratio(mixed_ratio)
        self.adaptive = bool(adaptive)
        self.adaptive_threshold = _require_int(
            'adaptive_threshold', adaptive_threshold, 1
        )
        self.adaptive_extra_questions = _require_int(
            'adaptive_extra_questions', adaptive_extra_questions, 0
        )
        self.questions_images = bool(questions_images)
        self._warned_no_rotation = False
        self.images_cache_dir = images_cache_dir
        self.images_prefix = images_prefix or DEFAULT_IMAGES_PREFIX

    # ── Политика сегментов ───────────────────────────────────────────────────

    def decide(self, detect_result) -> Decision:
        """
        Решает, что делать с запросом, и учитывает метрики.

        Порядок: для сработавших сигналов берётся первое действие, отличное от
        ``allow``. ``challenge`` при ``sample_rate < 1`` может превратиться в
        ``monitor`` — запрос пропускается, но попадает в shadow-статистику.

        Пример:
            decision = engine.decide(detect(headers))
            if decision.action == 'challenge':
                return redirect('/kremle/challenge')
        """
        hits = list(reasons_from_hits(
            browser=getattr(detect_result, 'browser', False),
            bot=getattr(detect_result, 'bot', False),
            referrer=getattr(detect_result, 'referrer', False),
            client_hints=getattr(detect_result, 'client_hints', False),
        ))

        if not hits:
            self.metrics.count_allow()
            return Decision(ALLOW, None)

        action = ALLOW
        for reason in hits:
            candidate = self.policy.get(reason, CHALLENGE)
            if candidate != ALLOW:
                action = candidate
                break

        sampled = True
        if action == CHALLENGE and self.sample_rate < 1.0:
            sampled = self._rng.random() < self.sample_rate
            if not sampled:
                action = MONITOR

        for reason in hits:
            self.metrics.count_detect(reason, action)

        main_reason = getattr(detect_result, 'reason', None) or hits[0]
        if action == MONITOR:
            logger.info(
                'Shadow detect (monitor): reason=%s sample_rate=%.2f',
                main_reason, self.sample_rate,
            )
            self.storage.log_event({
                'ts': time.time(), 'event': 'shadow',
                'ip': None, 'reason': main_reason,
            })
        return Decision(action, main_reason, sampled=sampled)

    def record_decision(self, decision: Decision, ip: Optional[str] = None) -> None:
        """Дописать IP в лог shadow-события и вызвать on_detect при блокировке."""
        if decision.action == ALLOW or decision.reason is None:
            return
        self.storage.log_event({
            'ts': time.time(),
            'event': 'shadow' if decision.action == MONITOR else 'detect',
            'ip': ip,
            'reason': decision.reason,
            'action': decision.action,
        })
        if decision.action in (CHALLENGE, 'block'):
            if self.on_detect:
                self.on_detect(
                    type('DetectSummary', (), {'reason': decision.reason})(),
                    ip,
                )

    # ── Ротация вопросов ─────────────────────────────────────────────────────

    def _rotation_key(self) -> str:
        """Ключ в storage: у разных наборов категорий своя история."""
        digest = hashlib.sha1(','.join(sorted(self.categories)).encode()).hexdigest()[:12]
        return f'recentq:{digest}'

    def _recent_keys(self) -> set:
        """Тексты недавно показанных вопросов. Ошибки storage не ломают капчу."""
        try:
            data = self.storage.get(self._rotation_key())
        except Exception as exc:  # noqa: BLE001 — хранилище может быть недоступно
            logger.debug('Ротация вопросов: storage недоступен (%s)', exc)
            return set()
        if not isinstance(data, dict):
            return set()
        texts = data.get('texts')
        return set(texts) if isinstance(texts, list) else set()

    def _rotate_pool(self, pool: List[dict]) -> List[dict]:
        """
        Пул без недавно показанных вопросов.

        Если «свежих» не хватает на челлендж, отдаём весь пул: повтор лучше,
        чем капча из двух вопросов.
        """
        recent = self._recent_keys()
        if not recent:
            return pool
        fresh = [q for q in pool if _question_key(q) not in recent]
        return fresh if len(fresh) >= self.question_count else pool

    def _remember_questions(self, questions: List[dict]) -> None:
        """Запомнить показанные вопросы (для ротации)."""
        try:
            data = self.storage.get(self._rotation_key())
        except Exception:  # noqa: BLE001 — не критично для выдачи капчи
            data = None
        texts = list(data.get('texts') or []) if isinstance(data, dict) else []
        known = set(texts)
        for question in questions:
            key = _question_key(question)
            if key and key not in known:
                known.add(key)
                texts.append(key)
        try:
            self.storage.set(
                self._rotation_key(),
                {'texts': texts[-RECENT_QUESTIONS_LIMIT:]},
                RECENT_QUESTIONS_TTL,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug('Ротация вопросов: не удалось сохранить историю (%s)', exc)

    def questions_health(
        self, stale_after_hours: float = DEFAULT_STALE_CACHE_HOURS
    ) -> Dict[str, object]:
        """
        Состояние банка вопросов для /kremle/health.

        Отвечает на вопрос, который обычный health пропускает: сколько
        вопросов есть на самом деле и когда последний раз обновлялся кеш
        «Решу ЕГЭ».

        Пример:
            engine.questions_health()['age_hours']   # 51.2 — кеш устарел
        """
        return questions_health(
            categories=self.categories,
            source=self.questions_source,
            allow_images=self.questions_images,
            extra_questions=self.extra_questions,
            only_extra=self.only_extra,
            stale_after_hours=stale_after_hours,
        )

    # ── Адаптивная сложность ─────────────────────────────────────────────────

    def fail_streak(self, ip: str) -> int:
        """
        Сколько провалов подряд набрал IP (0 — чистая история).

        Счётчик живёт ``ADAPTIVE_STREAK_TTL`` и сбрасывается первым успехом.
        Он отдельный от rate limit: там лимит на блокировку, здесь — на
        сложность.
        """
        if not self.adaptive or not ip:
            return 0
        return int(self.storage.get_counter(f'streak:{ip}') or 0)

    def _track_streak_fail(self, ip: Optional[str]) -> None:
        """Учесть провал в серии (для адаптивной сложности)."""
        if not self.adaptive or not ip:
            return
        self.storage.increment(f'streak:{ip}', ADAPTIVE_STREAK_TTL)

    def _reset_streak(self, ip: Optional[str]) -> None:
        """Успех обнуляет серию: наказывать за прошлое больше не за что."""
        if ip:
            self.storage.delete(f'streak:{ip}')

    def adaptive_level(self, ip: Optional[str] = None) -> int:
        """
        Ступень ужесточения для IP: 0 — обычная капча, дальше строже.

        Три провала подряд (``adaptive_threshold``) — первая ступень, шесть —
        вторая, но не выше ``ADAPTIVE_MAX_LEVEL``.
        """
        if not self.adaptive or not ip:
            return 0
        return min(self.fail_streak(ip) // self.adaptive_threshold, ADAPTIVE_MAX_LEVEL)

    def difficulty(self, ip: Optional[str] = None) -> Dict[str, int]:
        """
        Сколько вопросов и какой порог ошибок получит этот IP.

        Пример:
            engine.difficulty(ip)   # {'level': 0, 'question_count': 5, 'max_errors': 2}
        """
        level = self.adaptive_level(ip)
        count = self.question_count + level * self.adaptive_extra_questions
        return {
            'level': level,
            'question_count': count,
            'max_errors': max(0, self.max_errors - level),
        }

    def create_challenge(self, ip: Optional[str] = None) -> Challenge:
        """
        Создаёт новый набор вопросов.

        Args:
            ip: IP клиента. Нужен адаптивной сложности: после серии провалов
                челлендж приходит длиннее и со строгим порогом. Без IP —
                обычная капча.
        """
        # Трейс для тех, у кого стоит [otel]; без него — no-op. Токен и IP
        # сюда не пишем: первый — секрет, второй — персональные данные.
        with span('kremle.challenge') as current:
            challenge = self._create_challenge(ip)
            if current is not None:
                current.set_attribute('questions', len(challenge.questions))
                current.set_attribute(
                    'max_errors',
                    challenge.max_errors if challenge.max_errors is not None else -1,
                )
                current.set_attribute('source', self.questions_source)
            return challenge

    def _create_challenge(self, ip: Optional[str] = None) -> Challenge:
        """Тело ``create_challenge`` без трейса: один спан на операцию."""
        if self.only_extra:
            if not self.extra_questions:
                raise ValueError(
                    'only_extra=True но extra_questions пуст — нечего показывать'
                )
            pool = [dict(q, source_kind=q.get('source_kind', 'own'))
                    for q in self.extra_questions]
        else:
            pool = get_questions(
                categories=self.categories,
                count=None,
                shuffle=False,
                source=self.questions_source,
                allow_images=self.questions_images,
                mixed_ratio=self.mixed_ratio,
            )
            for q in self.extra_questions:
                entry = dict(q)
                entry.setdefault('category', 'custom')
                entry.setdefault('source_kind', 'own')
                pool.append(entry)

        # Один и тот же вопрос дважды в одной капче — это не проверка, а
        # потерянное время (кеш «Решу ЕГЭ» может содержать повторы).
        pool = _dedupe_questions(pool)

        # Адаптивная сложность: серия провалов делает капчу длиннее и строже.
        # Считаем один раз, чтобы один челлендж не оказался наполовину строгим.
        plan = self.difficulty(ip)
        challenge_count = min(plan['question_count'], len(pool))
        challenge_max_errors = plan['max_errors']
        if plan['level']:
            logger.info(
                'Adaptive difficulty: ip=%s level=%d questions=%d max_errors=%d',
                ip, plan['level'], challenge_count, challenge_max_errors,
            )

        # Ротация: сначала вопросы, которых не было в последних челленджах.
        # Без неё маленький банк (15 встроенных вопросов) выдаёт один и тот же
        # набор каждый раз — бот, один раз посмотревший ответы, проходит всегда.
        rotation_possible = len(pool) > challenge_count
        if rotation_possible:
            pool = self._rotate_pool(pool)

        if self.questions_source == MIXED_SOURCE and not self.only_extra:
            # Пропорция соблюдается на этапе выдачи: пул уже прошёл дедуп и
            # ротацию, делим его по происхождению и добираем по mixed_ratio.
            questions = mix_questions(
                [q for q in pool if q.get('source_kind') == 'own'],
                [q for q in pool if q.get('source_kind') == 'sdamgia'],
                challenge_count,
                self.mixed_ratio,
                rng=self._rng,
            )
        else:
            self._rng.shuffle(pool)
            questions = pool[:challenge_count]

        if rotation_possible:
            self._remember_questions(questions)
        elif not self._warned_no_rotation:
            self._warned_no_rotation = True
            logger.warning(
                'Пул из %d вопрос(ов) при question_count=%d: каждый челлендж '
                'содержит все вопросы, ротация невозможна. Уменьшите '
                'question_count или загрузите больше заданий '
                '(`kremle-detect questions sync`).',
                len(pool), challenge_count,
            )

        # Картинки из кеша отдаём своим роутом: иначе каждый показ капчи
        # сообщает порталу IP пользователя (и ломается, если портал закрыл
        # хотлинк). Нет файла в кеше — остаётся исходная ссылка.
        if self.questions_images and any(q.get('images') for q in questions):
            questions = _rewrite_images(
                questions, cache_dir=self.images_cache_dir, prefix=self.images_prefix,
            )

        # Пул может оказаться меньше question_count (мало категорий/своих вопросов).
        # Проверка реального числа вопросов — в verify(): лимит ошибок там
        # подрезается до len(questions) - 1. Здесь только предупреждаем.
        if len(questions) <= challenge_max_errors and not self._warned_small_pool:
            self._warned_small_pool = True
            logger.warning(
                'В пуле %d вопрос(ов), а max_errors=%d — лимит ошибок будет '
                'уменьшен до %d. Добавьте категории/свои вопросы или уменьшите '
                'max_errors.',
                len(questions), challenge_max_errors, max(len(questions) - 1, 0),
            )

        # Перемешиваем варианты ответов на сервере: индекс правильного ответа
        # меняется от челленджа к челленджу (боты не могут всегда отправлять 0).
        for q in questions:
            correct_text = q['opts'][q['ans']]
            shuffled = q['opts'][:]
            self._rng.shuffle(shuffled)
            q['opts'] = shuffled
            q['ans'] = shuffled.index(correct_text)

        challenge = Challenge(
            questions,
            self.secret,
            max_errors=min(challenge_max_errors, max(len(questions) - 1, 0)),
        )

        self.storage.set(
            f'challenge:{challenge.token}',
            challenge._serialize(),
            TOKEN_TTL,
        )

        self.metrics.count_challenge()
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
        signed = f'{answers_str}:{data["created_at"]}'
        # проверяем всеми действующими ключами: старый ещё принимается, пока
        # его не убрали из списка (ротация без разрыва активных капч)
        if not any(hmac.compare_digest(_sign(signed, key), token) for key in self.secrets):
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

    def _track_rate_attempt(self, ip: Optional[str]) -> None:
        """Учесть неудачную проверку в счётчике rate limit."""
        if self.rate_limit <= 0 or not ip:
            return
        self.storage.increment(f'rate:{ip}', self.rate_window)

    def _clear_rate_attempts(self, ip: Optional[str]) -> None:
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

    def _track_fail(self, ip: Optional[str]) -> None:
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

    def _track_pass(self, ip: Optional[str]) -> None:
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
        with span('kremle.verify') as current:
            result = self._verify(token, answers, ip=ip, fingerprint=fingerprint)
            if current is not None:
                current.set_attribute('passed', bool(result.get('passed')))
                current.set_attribute('errors', result.get('errors', -1))
                current.set_attribute('total', result.get('total', 0))
                current.set_attribute('max_errors', result.get('max_errors', -1))
                if result.get('error'):
                    current.set_attribute('error', str(result['error']))
            return result

    def _verify(
        self,
        token: str,
        answers: Dict[str, Any],
        ip: Optional[str] = None,
        fingerprint: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Тело ``verify`` без трейса: один спан на операцию."""
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

        self.metrics.count_verify()

        # Blacklist
        if ip and self.is_blacklisted(ip):
            self.metrics.count_blocked('blacklisted')
            logger.warning('Verify blocked by blacklist: ip=%s', ip)
            self.storage.log_event({'ts': time.time(), 'event': 'blocked', 'ip': ip, 'reason': 'blacklisted'})
            return {'passed': False, 'errors': -1, 'total': 0, 'error': 'blacklisted'}

        # Rate limiting
        if ip and self.check_rate_limit(ip):
            self.metrics.count_blocked('rate_limited')
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
        # Порог, с которым челлендж выдан: адаптивная сложность могла его
        # ужесточить, а фингерпринт — ужесточить ещё сильнее. Берём строгий из
        # двух: прощать то, что человеку обещали не прощать, нельзя.
        if challenge.max_errors is not None:
            effective_max_errors = min(effective_max_errors, challenge.max_errors)
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
            self._reset_streak(ip)
            self.metrics.count_pass()
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
            self._track_streak_fail(ip)
            self.metrics.count_fail()
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
            # Порог, который видел человек: тот, с которым выдан челлендж, и
            # «не больше total-1». Скрытое ужесточение по фингерпринту сюда не
            # попадает — о нём клиенту знать не нужно (это была бы подсказка
            # ботам), а обещанный порог остаётся честным.
            'max_errors': min(
                challenge.max_errors if challenge.max_errors is not None
                else self.max_errors,
                max(total - 1, 0),
            ),
        }

    def notify_detect(self, detect_result, ip: Optional[str] = None) -> None:
        """Вызвать callback при детекции (используется интеграциями)."""
        logger.info('Yandex detected: ip=%s reason=%s', ip, detect_result.reason)
        self.storage.log_event({
            'ts': time.time(), 'event': 'detect',
            'ip': ip, 'reason': detect_result.reason,
        })
        if self.on_detect:
            self.on_detect(detect_result, ip)
