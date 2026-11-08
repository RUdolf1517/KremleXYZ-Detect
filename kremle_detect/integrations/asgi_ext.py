# -*- coding: utf-8 -*-
"""
Starlette и Litestar: капча как первоклассная интеграция.

Обе библиотеки — чистый ASGI, поэтому логика живёт здесь одна на двоих:
обработчики работают с ASGI ``scope`` напрямую, а адаптеры только раскладывают
результат по своим типам ответов. Роуты и семантика повторяют
:mod:`kremle_detect.integrations.fastapi_ext` — тот же протокол, те же заголовки,
тот же ``/kremle/health``.

Starlette::

    from starlette.applications import Starlette
    from kremle_detect.integrations.asgi_ext import KremleStarlette

    app = Starlette()
    kremle = KremleStarlette(app, secret='свой-ключ')

Litestar::

    from litestar import Litestar
    from kremle_detect.integrations.asgi_ext import KremleLitestar

    kremle = KremleLitestar(secret='свой-ключ')
    app = Litestar(route_handlers=kremle.route_handlers,
                   middleware=kremle.middleware)

Сессии: обе интеграции рассчитывают на ``SessionMiddleware`` (в Starlette —
``starlette.middleware.sessions``, в Litestar — ``litestar.middleware.session``),
которая кладёт словарь в ``scope['session']``. Если middleware нет, капча
работает, но «пройдено» не запоминается — и об этом пишется предупреждение.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import (
    TYPE_CHECKING, Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple,
)

from .. import __version__
from ..captcha import CaptchaEngine
from ..detector import detect
from ..images import RESPONSE_HEADERS as IMAGE_RESPONSE_HEADERS, read_image
from ..ip import client_ip, ip_matches
from ..metrics import health_payload
from ..session import (
    DEFAULT_PENDING_TTL, NEXT_KEY, SESSION_KEY, TOKEN_KEY, build_verification,
    clear_pending, is_verified, mark_pending, pending_reason, remaining_seconds,
)
from ..storage import BaseStorage, MemoryStorage, RedisStorage
from ..widget import headers as widget_headers, read_bundle
from ._common import (
    accepts_json,
    blocked_payload,
    captcha_headers,
    challenge_payload,
    no_store_headers,
    is_document_request,
    render_captcha_html,
    wants_json,
)

logger = logging.getLogger('kremle')

if TYPE_CHECKING:  # pragma: no cover - только для типов, litestar не нужен в рантайме
    from litestar import Request as LitestarRequest, Response as LitestarResponse

#: Префикс всех служебных роутов.
PREFIX = '/kremle'

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates')

Header = Tuple[bytes, bytes]


# ── минимальный слой над ASGI ────────────────────────────────────────────────

class ASGIRequest:
    """Только то, что нужно капче: путь, метод, заголовки, тело, сессия."""

    def __init__(self, scope: Mapping[str, Any], receive: Optional[Callable] = None,
                 body: Optional[bytes] = None):
        self.scope = scope
        self._receive = receive
        self._body = body
        self.method = scope.get('method', 'GET').upper()
        self.path = scope.get('path', '') or ''
        self.query_string = (scope.get('query_string') or b'').decode('latin-1')
        self.headers: Dict[str, str] = {
            key.decode('latin-1').lower(): value.decode('latin-1')
            for key, value in (scope.get('headers') or [])
        }

    @property
    def session(self) -> dict:
        """Словарь сессии от SessionMiddleware (или пустой, если её нет)."""
        session = self.scope.get('session')
        return session if isinstance(session, dict) else {}

    @property
    def peer(self) -> str:
        client = self.scope.get('client') or ('', 0)
        return client[0] or ''

    def ip(self, trusted_proxies=None) -> str:
        return client_ip(self.peer, self.headers.get('x-forwarded-for', ''), trusted_proxies)

    async def body(self) -> bytes:
        if self._body is not None:
            return self._body
        self._body = await read_body(self._receive)
        return self._body

    async def json(self) -> Any:
        body = await self.body()
        if not body:
            return None
        return json.loads(body.decode('utf-8'))


class ASGIResponse:
    """Готовый ответ: статус, заголовки, тело — без привязки к фреймворку."""

    def __init__(self, body: Any = b'', status: int = 200,
                 headers: Optional[Dict[str, str]] = None, content_type: str = 'text/plain'):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
            content_type = 'application/json'
        elif isinstance(body, str):
            body = body.encode('utf-8')
        self.body: bytes = body or b''
        self.status = status
        self.headers: Dict[str, str] = {'Content-Type': content_type}
        self.headers.update(headers or {})

    @property
    def header_items(self) -> List[Header]:
        return [(key.lower().encode('latin-1'), value.encode('latin-1'))
                for key, value in self.headers.items()]

    async def send(self, send: Callable) -> None:
        await send({
            'type': 'http.response.start',
            'status': self.status,
            'headers': self.header_items,
        })
        await send({'type': 'http.response.body', 'body': self.body})


def json_response(payload: Any, status: int = 200,
                  headers: Optional[Dict[str, str]] = None) -> ASGIResponse:
    return ASGIResponse(payload, status=status, headers=headers,
                        content_type='application/json; charset=utf-8')


def text_response(text: str, status: int = 200,
                  headers: Optional[Dict[str, str]] = None) -> ASGIResponse:
    return ASGIResponse(text, status=status, headers=headers,
                        content_type='text/plain; charset=utf-8')


def html_response(html: str, headers: Optional[Dict[str, str]] = None) -> ASGIResponse:
    return ASGIResponse(html, headers=headers,
                        content_type='text/html; charset=utf-8')


def redirect_response(location: str, status: int = 302,
                      headers: Optional[Dict[str, str]] = None) -> ASGIResponse:
    merged = {'Location': location}
    merged.update(headers or {})
    return ASGIResponse(b'', status=status, headers=merged)


async def read_body(receive: Optional[Callable]) -> bytes:
    if receive is None:
        return b''
    body = b''
    while True:
        message = await receive()
        if message.get('type') != 'http.request':
            break
        body += message.get('body', b'')
        if not message.get('more_body'):
            break
    return body


# ── общая логика капчи для обоих фреймворков ─────────────────────────────────

def _storage_name(storage: BaseStorage) -> str:
    if isinstance(storage, RedisStorage):
        return 'redis'
    if isinstance(storage, MemoryStorage):
        return 'memory'
    return type(storage).__name__


class KremleASGI:
    """
    Общее ядро интеграций Starlette и Litestar.

    Не используется напрямую: ``KremleStarlette`` и ``KremleLitestar`` — тонкие
    обёртки над этим классом.
    """

    def __init__(
        self,
        categories: Optional[Sequence[str]] = None,
        question_count: int = 15,
        max_errors: int = 3,
        secret: str | Sequence[str] = 'kremle-default-secret',
        skip_paths: Optional[Sequence[str]] = None,
        storage: Optional[BaseStorage] = None,
        rate_limit: int = 10,
        rate_window: int = 600,
        whitelist: Optional[List[str]] = None,
        template: Optional[str] = None,
        on_detect: Optional[Callable] = None,
        on_pass: Optional[Callable] = None,
        on_fail: Optional[Callable] = None,
        extra_questions: Optional[list] = None,
        only_extra: bool = False,
        fail_threshold: int = 0,
        blacklist_ttl: int = 86400,
        trusted_proxies: Optional[Sequence[str]] = None,
        challenge_rate_limit: int = 60,
        policy: Optional[dict] = None,
        sample_rate: float = 1.0,
        metrics_enabled: bool = True,
        verified_ttl: int = 86400,
        bind_ip: bool = False,
        bind_ua: bool = False,
        questions_source: str = 'auto',
        mixed_ratio: float = 0.5,
        questions_images: bool = False,
        images_cache_dir: Optional[str] = None,
        images_prefix: str = '/kremle/img/',
        csp_policy: Optional[str] = None,
        json_api: bool = True,
        headless: bool = False,
        adaptive: bool = True,
        adaptive_threshold: int = 3,
        adaptive_extra_questions: int = 2,
        sticky_referrer: bool = True,
        sticky_ttl: int = DEFAULT_PENDING_TTL,
        overlay: bool = False,
        enable_ops_routes: bool = True,
    ):
        self.engine = CaptchaEngine(
            categories=categories,
            question_count=question_count,
            max_errors=max_errors,
            secret=secret,
            storage=storage,
            rate_limit=rate_limit,
            rate_window=rate_window,
            on_detect=on_detect,
            on_pass=on_pass,
            on_fail=on_fail,
            extra_questions=extra_questions,
            only_extra=only_extra,
            fail_threshold=fail_threshold,
            blacklist_ttl=blacklist_ttl,
            challenge_rate_limit=challenge_rate_limit,
            policy=policy,
            sample_rate=sample_rate,
            metrics_enabled=metrics_enabled,
            verified_ttl=verified_ttl,
            bind_ip=bind_ip,
            bind_ua=bind_ua,
            questions_source=questions_source,
            mixed_ratio=mixed_ratio,
            questions_images=questions_images,
            images_cache_dir=images_cache_dir,
            images_prefix=images_prefix,
            adaptive=adaptive,
            adaptive_threshold=adaptive_threshold,
            adaptive_extra_questions=adaptive_extra_questions,
        )
        self.skip_paths = list(skip_paths or ['/docs', '/openapi.json', '/redoc', '/schema'])
        self.whitelist = whitelist or []
        self.custom_template = template
        self.secret = secret[0] if isinstance(secret, (list, tuple)) else secret
        self.headless = headless
        self.json_api = json_api
        self.sticky_referrer = bool(sticky_referrer)
        self.sticky_ttl = int(sticky_ttl)
        self.overlay = bool(overlay)
        self.csp_policy = csp_policy
        self.enable_ops_routes = enable_ops_routes
        self.trusted_proxies = None if trusted_proxies is None else list(trusted_proxies)

    # ── вспомогательное ──────────────────────────────────────────────────────

    async def _run(self, func: Callable, *args, **kwargs):
        """
        Синхронный движок внутри async-обработчика.

        Redis-клиент и чтение кеша — блокирующие: в event loop их нельзя, иначе
        один медленный ответ встаёт поперёк всех остальных.
        """
        return await asyncio.to_thread(func, *args, **kwargs)

    def _wants_json(self, request: ASGIRequest) -> bool:
        if self.headless:
            return True
        if not self.json_api:
            return False
        return wants_json(
            request.headers.get('accept'),
            request.headers.get('x-requested-with'),
            request.path,
        )

    def _is_document(self, request: ASGIRequest) -> bool:
        """Переход по ссылке, а не подзагрузка и не API-вызов."""
        return is_document_request(
            request.headers.get('accept'),
            request.headers.get('x-requested-with'),
            request.method,
            request.headers.get('sec-fetch-dest'),
        )

    def _is_verified(self, request: ASGIRequest, ip: Optional[str] = None) -> bool:
        session = request.session
        state = session.get(SESSION_KEY)
        ok = is_verified(
            state,
            ip=ip,
            ua=request.headers.get('user-agent'),
            bind_ip=self.engine.bind_ip,
            bind_ua=self.engine.bind_ua,
        )
        if not ok and state is not None:
            session.pop(SESSION_KEY, None)
        return ok

    def is_own_path(self, path: str) -> bool:
        """Служебный путь капчи или явно пропускаемый."""
        return path.startswith(PREFIX + '/') or any(
            path.startswith(item) for item in self.skip_paths
        )

    # ── guard ────────────────────────────────────────────────────────────────

    async def guard(self, request: ASGIRequest) -> Optional[ASGIResponse]:
        """
        Решение по запросу: ``None`` — пропустить, иначе готовый ответ.

        Ровно та же логика, что в Flask/Django/FastAPI: whitelist, blocklist,
        политика сегментов, monitor, block, challenge.
        """
        engine = self.engine
        if self.is_own_path(request.path):
            return None

        ip = request.ip(self.trusted_proxies)

        if self._is_verified(request, ip=ip):
            return None

        if self.whitelist and ip_matches(ip, self.whitelist):
            return None
        if await self._run(engine.is_whitelisted, ip):
            return None

        await self._run(engine.metrics.count_request)

        if await self._run(engine.is_blacklisted, ip):
            await self._run(engine.metrics.count_blocked, 'blacklisted')
            if self._wants_json(request):
                return json_response(blocked_payload('blacklisted'), 403, no_store_headers())
            return text_response('Доступ заблокирован.', 403)

        headers = {
            'User-Agent': request.headers.get('user-agent', ''),
            'Referer': request.headers.get('referer', ''),
            'Sec-CH-UA': request.headers.get('sec-ch-ua', ''),
            'Sec-CH-UA-Full-Version-List': request.headers.get(
                'sec-ch-ua-full-version-list', ''
            ),
        }
        detection = detect(headers)
        decision = await self._run(engine.decide, detection)
        await self._run(engine.record_decision, decision, ip)

        if decision.action == 'monitor':
            return None
        if decision.action == 'block':
            if self._wants_json(request):
                return json_response(
                    blocked_payload(decision.reason or 'blocked'), 403, no_store_headers()
                )
            return text_response('Доступ заблокирован.', 403)

        if decision.action == 'challenge':
            request.session[NEXT_KEY] = request.path
            if self.overlay:
                # «Поверх страницы»: долг ставим при любом сигнале, а переход
                # по ссылке пропускаем — окно покажет капчу поверх оболочки.
                mark_pending(request.session, decision.reason, self.sticky_ttl)
                if self._is_document(request):
                    return None
            elif self.sticky_referrer and detection.referrer:
                # Referer поисковика приходит только с первым запросом: без
                # записи в сессии капча обходится стиранием её адреса.
                mark_pending(request.session, decision.reason, self.sticky_ttl)
            return self._challenge_response(request, decision.reason)

        if decision.action != 'allow':
            # неизвестное действие политики не блокируем
            return None

        # Сигналов нет, но сессия помнит «долг капчи» — держим, пока не пройдут.
        sticky = self.sticky_referrer or self.overlay
        reason = pending_reason(request.session, self.sticky_ttl) if sticky else None
        if reason:
            await self._run(engine.metrics.count_detect, reason, 'challenge')
            if self.overlay and self._is_document(request):
                return None
            return self._challenge_response(request, reason)
        return None

    def _challenge_response(self, request: ASGIRequest,
                            reason: Optional[str]) -> ASGIResponse:
        """Капча: JSON для API-клиента, редирект для браузера."""
        request.session[NEXT_KEY] = request.path
        if self._wants_json(request):
            return json_response(challenge_payload(reason), 403, no_store_headers())
        return redirect_response(PREFIX + '/challenge', 302)

    async def __call__(self, scope: dict, receive: Callable, send: Callable,
                       next_app: Callable) -> None:
        """ASGI-middleware: пропустить или ответить капчей."""
        if scope['type'] != 'http':
            await next_app(scope, receive, send)
            return
        request = ASGIRequest(scope, receive)
        response = await self.guard(request)
        if response is None:
            await next_app(scope, receive, send)
        else:
            await response.send(send)

    # ── роуты ────────────────────────────────────────────────────────────────

    async def challenge(self, request: ASGIRequest) -> ASGIResponse:
        engine = self.engine
        ip = request.ip(self.trusted_proxies)
        if await self._run(engine.check_challenge_limit, ip):
            return json_response(
                {'error': 'too_many_requests'},
                429,
                {'Cache-Control': 'no-store', 'Retry-After': str(engine.rate_window)},
            )
        await self._run(engine.track_challenge, ip)

        ch = await self._run(engine.create_challenge, ip)
        request.session[TOKEN_KEY] = ch.token
        data = ch.to_dict(verify_url=PREFIX + '/verify', max_errors=ch.max_errors)
        headers = captcha_headers(self.csp_policy)

        if self.headless or accepts_json(request.headers.get('accept', '')):
            return json_response(data, headers=headers)

        template_path = self.custom_template or os.path.join(TEMPLATE_DIR, 'kremle_captcha.html')
        try:
            with open(template_path, encoding='utf-8') as handle:
                html = handle.read()
        except OSError as exc:
            raise RuntimeError(
                f'Не удалось открыть шаблон капчи: {template_path!r} — {exc}'
            ) from exc
        return html_response(render_captcha_html(html, data), headers)

    async def verify(self, request: ASGIRequest) -> ASGIResponse:
        engine = self.engine
        try:
            data = await request.json()
        except (ValueError, TypeError, UnicodeDecodeError):
            return json_response({'error': 'invalid_json'}, 400)
        if not isinstance(data, dict):
            return json_response({'error': 'invalid_json'}, 400)

        token = data.get('token') or request.session.get(TOKEN_KEY, '')
        answers = data.get('answers', {})
        fingerprint = data.get('fingerprint')
        ip = request.ip(self.trusted_proxies)

        result = await self._run(engine.verify, token, answers, ip=ip,
                                 fingerprint=fingerprint)
        request.session.pop(TOKEN_KEY, None)

        if result['passed']:
            clear_pending(request.session)
            request.session[SESSION_KEY] = build_verification(
                ip=ip,
                ua=request.headers.get('user-agent'),
                ttl=engine.verified_ttl,
            )
            result['redirect'] = request.session.pop(NEXT_KEY, '/')
        else:
            result['redirect'] = None

        return json_response(result, headers=captcha_headers(self.csp_policy))

    async def status(self, request: ASGIRequest) -> ASGIResponse:
        state = request.session.get(SESSION_KEY)
        # Тот же IP и те же привязки, что у гарда: иначе при bind_ip окно
        # поверх страницы не открывалось после смены адреса.
        verified = is_verified(
            state,
            ip=request.ip(self.trusted_proxies),
            ua=request.headers.get('user-agent'),
            bind_ip=self.engine.bind_ip,
            bind_ua=self.engine.bind_ua,
        )
        sticky = self.sticky_referrer or self.overlay
        pending = None if verified else pending_reason(
            request.session, self.sticky_ttl if sticky else None)
        return json_response(
            {
                'verified': verified,
                'expires_in': remaining_seconds(state),
                'pending': bool(pending),
                'reason': pending,
                'challenge_url': PREFIX + '/challenge' if pending else None,
                'overlay': self.overlay,
            },
            headers=captcha_headers(self.csp_policy),
        )

    async def logout(self, request: ASGIRequest) -> ASGIResponse:
        session = request.session
        session.pop(SESSION_KEY, None)
        session.pop(TOKEN_KEY, None)
        session.pop(NEXT_KEY, None)
        # Долг капчи переживает выход: иначе /kremle/logout = «отмени капчу».
        return json_response({'verified': False}, headers=captcha_headers(self.csp_policy))

    async def widget(self, name: str) -> ASGIResponse:
        payload = await self._run(read_bundle, name)
        if payload is None:
            return text_response(
                'Виджет не собран. В исходниках: cd kremle-widget && npm run build',
                404,
                {'Cache-Control': 'no-store'},
            )
        return ASGIResponse(payload, headers=widget_headers(),
                            content_type=widget_headers()['Content-Type'])

    async def image(self, key: str) -> ASGIResponse:
        entry = await self._run(read_image, key, self.engine.images_cache_dir)
        if entry is None:
            return ASGIResponse(b'', 404, {'Cache-Control': 'no-store'})
        headers = dict(IMAGE_RESPONSE_HEADERS)
        headers['Content-Type'] = entry['content_type']
        return ASGIResponse(entry['bytes'], headers=headers)

    async def health(self) -> ASGIResponse:
        storage = self.engine.storage
        payload = await self._run(
            health_payload,
            version=__version__,
            storage=storage,
            storage_name=_storage_name(storage),
            questions=await self._run(self.engine.questions_health),
            extra={
                'sample_rate': self.engine.sample_rate,
                'policy': dict(self.engine.policy),
                'verified_ttl': self.engine.verified_ttl,
                'questions_source': self.engine.questions_source,
                'questions_images': self.engine.questions_images,
            },
        )
        return json_response(payload, 200 if payload['storage_ok'] else 503)

    async def stats(self) -> ASGIResponse:
        return json_response(await self._run(self.engine.metrics.snapshot))

    async def metrics(self) -> ASGIResponse:
        text = await self._run(self.engine.metrics.prometheus)
        return text_response(text, headers={'Content-Type':
                                            'text/plain; version=0.0.4; charset=utf-8'})

    async def dispatch(self, name: str, request: ASGIRequest,
                       path_params: Optional[Dict[str, str]] = None) -> ASGIResponse:
        """
        Вызвать обработчик по имени из :meth:`routes_table`.

        Единая точка для Starlette и Litestar: адаптеры знают только, как
        завернуть результат в свой тип ответа.
        """
        handler = getattr(self, name)
        if name in ('challenge', 'verify', 'status', 'logout'):
            return await handler(request)
        if name in ('widget', 'image'):
            params = path_params or {}
            value = params.get('name') or params.get('key') or ''
            return await handler(value)
        return await handler()

    def routes_table(self) -> List[Tuple[str, Tuple[str, ...], str]]:
        """
        Таблица роутов: (путь, методы, имя обработчика).

        Одна таблица на оба фреймворка — паритет роутов проверяется тестом, а не
        глазами.
        """
        table: List[Tuple[str, Tuple[str, ...], str]] = [
            (PREFIX + '/challenge', ('GET',), 'challenge'),
            (PREFIX + '/verify', ('POST',), 'verify'),
            (PREFIX + '/status', ('GET',), 'status'),
            (PREFIX + '/logout', ('POST',), 'logout'),
            (PREFIX + '/widget/{name}', ('GET',), 'widget'),
            (PREFIX + '/img/{key}', ('GET',), 'image'),
        ]
        if self.enable_ops_routes:
            table += [
                (PREFIX + '/health', ('GET',), 'health'),
                (PREFIX + '/stats', ('GET',), 'stats'),
                (PREFIX + '/metrics', ('GET',), 'metrics'),
            ]
        return table


# ── Starlette ────────────────────────────────────────────────────────────────

class KremleStarlette:
    """
    Капча для Starlette: guard-middleware и роуты капчи.

    Пример:
        from starlette.applications import Starlette
        from kremle_detect.integrations.asgi_ext import KremleStarlette

        app = Starlette()
        kremle = KremleStarlette(app, secret='свой-ключ')
    """

    def __init__(self, app=None, **options):
        self.core = KremleASGI(**options)
        self.engine = self.core.engine
        if app is not None:
            self.init_app(app)

    def init_app(self, app) -> None:
        from starlette.middleware.sessions import SessionMiddleware
        from starlette.responses import Response
        from starlette.routing import Route

        core = self.core

        def build(name: str):
            async def endpoint(request):
                path_params = request.path_params or {}
                body = await request.body() if name == 'verify' else None
                result = await core.dispatch(
                    name, ASGIRequest(request.scope, body=body), path_params
                )
                return Response(
                    content=result.body,
                    status_code=result.status,
                    headers=result.headers,
                )

            endpoint.__name__ = 'kremle_' + name
            return endpoint

        app.state.kremle = self
        for path, methods, name in core.routes_table():
            app.router.routes.append(
                Route(path, build(name), methods=list(methods), name='kremle_' + name)
            )

        class KremleGuardMiddleware:
            """ASGI-middleware: до всех остальных решает, пускать ли дальше."""

            def __init__(self, wrapped):
                self.app = wrapped

            async def __call__(self, scope, receive, send):
                await core(scope, receive, send, self.app)

        from starlette.middleware import Middleware

        # Сессия обязана стоять снаружи guard: иначе guard не увидит «пройдено»,
        # а записать «пройдено» ему будет некуда. Список user_middleware идёт
        # снаружи внутрь, а add_middleware вставляет в начало.
        session_index = next(
            (
                index
                for index, item in enumerate(getattr(app, 'user_middleware', []))
                if getattr(item, 'cls', None) is SessionMiddleware
            ),
            None,
        )
        if session_index is None:
            app.add_middleware(KremleGuardMiddleware)
            app.add_middleware(SessionMiddleware, secret_key=core.secret)
        else:
            app.user_middleware.insert(session_index + 1, Middleware(KremleGuardMiddleware))


# ── Litestar ─────────────────────────────────────────────────────────────────

class KremleLitestar:
    """
    Капча для Litestar: guard-middleware и route handlers.

    Пример:
        from litestar import Litestar
        from litestar.stores.memory import MemoryStore
        from kremle_detect.integrations.asgi_ext import KremleLitestar

        kremle = KremleLitestar(secret='свой-ключ')
        app = Litestar(
            route_handlers=kremle.route_handlers,
            middleware=kremle.middleware,          # guard + сессии
            stores={'sessions': MemoryStore()},    # или RedisStore в проде
        )
    """

    def __init__(self, app=None, **options):
        self.core = KremleASGI(**options)
        self.engine = self.core.engine
        if app is not None:
            self.init_app(app)

    def middleware_for(self):
        """
        Готовый список middleware: guard + серверные сессии капчи.

        Нужен ``stores={'sessions': ...}`` в приложении Litestar (или RedisStore):
        сессии хранятся на сервере, а не в подписанной куке.
        """
        from litestar.middleware import DefineMiddleware
        from litestar.middleware.session.server_side import ServerSideSessionConfig

        core = self.core

        class KremleGuardMiddleware:
            def __init__(self, app):
                self.app = app

            async def __call__(self, scope, receive, send):
                await core(scope, receive, send, self.app)

        session_config = ServerSideSessionConfig()
        # Порядок важен: Litestar применяет список снаружи внутрь, поэтому
        # сессия идёт первой. Иначе guard получает запрос, где
        # ``scope['session']`` ещё не существует, — и «капча пройдена» не
        # запоминается вовсе: человек проходит её заново на каждой странице.
        return [
            DefineMiddleware(session_config.middleware),
            DefineMiddleware(KremleGuardMiddleware),
        ]

    #: Синоним для ``Litestar(middleware=...)``.
    @property
    def middleware(self):
        return self.middleware_for()

    def route_handlers_list(self) -> list:
        """Обработчики роутов для ``Litestar(route_handlers=...)``."""
        from litestar import Request, Response, get, post

        core = self.core

        # Litestar разбирает аннотации обработчиков в пространстве имён модуля,
        # а импортировать litestar на уровне модуля незачем: для Flask-проекта
        # это лишняя зависимость. Поэтому кладём имена в globals() только когда
        # интеграция действительно используется.
        globals().update(LitestarRequest=Request, LitestarResponse=Response)

        def build(path: str, methods: Sequence[str], name: str):
            async def handler(request: LitestarRequest) -> LitestarResponse:  # noqa: F821
                path_params = dict(request.path_params or {})
                body = await request.body() if name == 'verify' else None
                result = await core.dispatch(
                    name, ASGIRequest(request.scope, body=body), path_params
                )
                return Response(
                    content=result.body,
                    status_code=result.status,
                    headers=result.headers,
                    media_type=result.headers.get('Content-Type', 'application/json'),
                )

            handler.__name__ = 'kremle_' + name
            decorator = post if 'POST' in methods else get
            # Litestar требует тип в параметре пути: {name:str}, а не {name}
            litestar_path = path.replace('{name}', '{name:str}').replace('{key}', '{key:str}')
            return decorator(litestar_path, name='kremle_' + name)(handler)

        return [build(path, methods, name) for path, methods, name in core.routes_table()]

    @property
    def route_handlers(self) -> list:
        """Синоним ``route_handlers_list()`` — для ``Litestar(route_handlers=...)``."""
        return self.route_handlers_list()

    def init_app(self, app) -> None:
        """Зарегистрировать роуты на уже созданном приложении Litestar."""
        app.state.kremle = self
        for handler in self.route_handlers_list():
            app.register(handler)


__all__ = [
    'ASGIRequest',
    'ASGIResponse',
    'KremleASGI',
    'KremleLitestar',
    'KremleStarlette',
    'html_response',
    'json_response',
    'redirect_response',
    'text_response',
]
