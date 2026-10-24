# -*- coding: utf-8 -*-
"""
FastAPI / Starlette интеграция KremleDetect.

Использование:
    from fastapi import FastAPI
    from kremle_detect.integrations.fastapi_ext import KremleFastAPI

    app = FastAPI()
    kremle = KremleFastAPI(app, categories=['math'], question_count=10, secret='...')

Тяжёлые синхронные вызовы (движок капчи, Redis) выполняются в threadpool,
чтобы не блокировать event loop: ``async_offload=True`` (по умолчанию).
"""

from __future__ import annotations

import json
import os
from typing import Callable, List, Optional, Sequence

from .. import __version__
from ..captcha import CaptchaEngine
from ..detector import detect
from ..images import RESPONSE_HEADERS as IMAGE_RESPONSE_HEADERS, read_image
from ..ip import client_ip, ip_matches
from ..metrics import health_payload
from ..session import (
    NEXT_KEY, SESSION_KEY, TOKEN_KEY, build_verification, is_verified, remaining_seconds,
)
from ..storage import BaseStorage, MemoryStorage, RedisStorage
from ._common import (
    accepts_json, blocked_payload, challenge_payload, no_store_headers, wants_json,
)

# FastAPI/Starlette are optional dependencies but this file is only imported
# when they are available.  Module-level imports are required so that FastAPI
# can resolve type annotations via func.__globals__ when registering routes
# that are defined inside init_app() closures.
try:
    from fastapi import Request
    from fastapi.responses import (
        HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response,
    )
    from starlette.concurrency import run_in_threadpool
    from starlette.middleware.sessions import SessionMiddleware
except ImportError:  # pragma: no cover - зависит от окружения
    # SessionMiddleware отсутствует, если не установлен itsdangerous: сам Starlette
    # импортируется вместе с fastapi, а его SessionMiddleware — нет.
    SessionMiddleware = None


def _ip_in_whitelist(ip: str, whitelist: list) -> bool:
    return ip_matches(ip, whitelist)


def _client_ip(request, trusted_proxies=None) -> str:
    """IP клиента; X-Forwarded-For учитывается только от доверенных прокси."""
    peer = request.client.host if request.client else ''
    return client_ip(peer, request.headers.get('x-forwarded-for', ''), trusted_proxies)


def _storage_name(storage: BaseStorage) -> str:
    if isinstance(storage, RedisStorage):
        return 'redis'
    if isinstance(storage, MemoryStorage):
        return 'memory'
    return type(storage).__name__


class KremleFastAPI:
    """
    FastAPI-интеграция.

    Добавляет middleware + роуты /kremle/challenge, /kremle/verify, /kremle/status,
    /kremle/logout, /kremle/health, /kremle/stats, /kremle/metrics.
    """

    def __init__(
        self,
        app=None,
        categories: Optional[Sequence[str]] = None,
        question_count: int = 15,
        max_errors: int = 3,
        secret: str = 'kremle-default-secret',
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
        headless: bool = False,
        trusted_proxies: Optional[Sequence[str]] = None,
        challenge_rate_limit: int = 60,
        policy: Optional[dict] = None,
        sample_rate: float = 1.0,
        metrics_enabled: bool = True,
        verified_ttl: int = 86400,
        bind_ip: bool = False,
        bind_ua: bool = False,
        questions_source: str = 'auto',
        questions_images: bool = False,
        images_cache_dir: Optional[str] = None,
        images_prefix: str = '/kremle/img/',
        json_api: bool = True,
        enable_ops_routes: bool = True,
        async_offload: bool = True,
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
            questions_images=questions_images,
            images_cache_dir=images_cache_dir,
            images_prefix=images_prefix,
        )
        self.skip_paths = list(skip_paths or ['/docs', '/openapi.json', '/redoc'])
        self.whitelist = whitelist or []
        self.custom_template = template
        self.secret = secret
        self.headless = headless
        self.json_api = json_api
        self.enable_ops_routes = enable_ops_routes
        self.async_offload = async_offload
        # None → авто (loopback + приватные сети), [] → не доверять никому
        self.trusted_proxies = None if trusted_proxies is None else list(trusted_proxies)
        self.bind_ip = bind_ip
        self.bind_ua = bind_ua

        if app is not None:
            self.init_app(app)

    # ── вспомогательное ──────────────────────────────────────────────────────

    async def _run(self, func, *args, **kwargs):
        """
        Выполняет синхронную операцию в threadpool (Redis/движок не блокируют
        event loop). При ``async_offload=False`` — вызывает напрямую.
        """
        if self.async_offload:
            return await run_in_threadpool(func, *args, **kwargs)
        return func(*args, **kwargs)

    def _wants_json(self, request) -> bool:
        if self.headless:
            return True
        if not self.json_api:
            return False
        return wants_json(
            request.headers.get('accept'),
            request.headers.get('x-requested-with'),
            request.url.path,
        )

    def _is_verified(self, request, ip: Optional[str] = None) -> bool:
        state = request.session.get(SESSION_KEY)
        ok = is_verified(
            state,
            ip=ip,
            ua=request.headers.get('user-agent'),
            bind_ip=self.bind_ip,
            bind_ua=self.bind_ua,
        )
        if not ok and state is not None:
            request.session.pop(SESSION_KEY, None)
        return ok

    # ── инициализация ────────────────────────────────────────────────────────

    def init_app(self, app) -> None:
        engine = self.engine
        skip_paths = self.skip_paths
        whitelist = self.whitelist
        custom_template = self.custom_template
        headless = self.headless
        trusted_proxies = self.trusted_proxies
        enable_ops = self.enable_ops_routes
        template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates')
        wants_json_fn = self._wants_json
        is_verified_fn = self._is_verified
        run = self._run

        @app.middleware('http')
        async def kremle_guard(request: Request, call_next):
            path = request.url.path

            if path.startswith('/kremle/') or any(path.startswith(s) for s in skip_paths):
                return await call_next(request)

            ip = _client_ip(request, trusted_proxies)

            if is_verified_fn(request, ip=ip):
                return await call_next(request)

            # IP whitelist / blacklist
            if whitelist and _ip_in_whitelist(ip, whitelist):
                return await call_next(request)
            if await run(engine.is_whitelisted, ip):
                return await call_next(request)

            await run(engine.metrics.count_request)

            if await run(engine.is_blacklisted, ip):
                await run(engine.metrics.count_blocked, 'blacklisted')
                if wants_json_fn(request):
                    return JSONResponse(blocked_payload('blacklisted'), status_code=403,
                                        headers=no_store_headers())
                return PlainTextResponse('Доступ заблокирован.', status_code=403)

            headers = {
                'User-Agent': request.headers.get('user-agent', ''),
                'Referer': request.headers.get('referer', ''),
                'Sec-CH-UA': request.headers.get('sec-ch-ua', ''),
                'Sec-CH-UA-Full-Version-List': request.headers.get(
                    'sec-ch-ua-full-version-list', ''
                ),
            }
            decision = await run(engine.decide, detect(headers))
            await run(engine.record_decision, decision, ip)

            if decision.action == 'monitor':
                return await call_next(request)
            if decision.action == 'block':
                if wants_json_fn(request):
                    return JSONResponse(blocked_payload(decision.reason or 'blocked'),
                                        status_code=403, headers=no_store_headers())
                return PlainTextResponse('Доступ заблокирован.', status_code=403)
            if decision.action == 'challenge':
                request.session[NEXT_KEY] = str(request.url)
                if wants_json_fn(request):
                    return JSONResponse(challenge_payload(decision.reason), status_code=403,
                                        headers=no_store_headers())
                return RedirectResponse('/kremle/challenge', status_code=302)

            return await call_next(request)

        @app.get('/kremle/challenge')
        async def kremle_challenge(request: Request):
            ip = _client_ip(request, trusted_proxies)
            if await run(engine.check_challenge_limit, ip):
                return JSONResponse(
                    {'error': 'too_many_requests'},
                    status_code=429,
                    # окно лимита известно — говорим клиенту, когда пробовать снова
                    headers={'Cache-Control': 'no-store',
                             'Retry-After': str(engine.rate_window)},
                )
            await run(engine.track_challenge, ip)

            ch = await run(engine.create_challenge)
            request.session[TOKEN_KEY] = ch.token

            # Относительный URL, а не абсолютный: request.url_for() собирает его
            # из Host, а за обратным прокси/в песочнице Host бывает внутренним
            # (127.0.0.1:8000). Тогда браузер стучится по этому адресу к себе
            # и капча «не отправляется» с ошибкой соединения.
            root_path = request.scope.get('root_path', '') or ''
            verify_url = root_path + str(request.app.url_path_for('kremle_verify'))

            # to_dict — чистая сериализация без I/O, threadpool не нужен
            data = ch.to_dict(verify_url=verify_url)
            no_store = no_store_headers()

            if headless or accepts_json(request.headers.get('accept', '')):
                return JSONResponse(data, headers=no_store)

            tpl_path = custom_template or os.path.join(template_dir, 'kremle_captcha.html')
            try:
                with open(tpl_path, encoding='utf-8') as f:
                    html = f.read()
            except OSError as e:
                raise RuntimeError(
                    f'Не удалось открыть шаблон капчи: {tpl_path!r} — {e}'
                ) from e

            html = html.replace(
                '{{ questions_json }}',
                json.dumps(data, ensure_ascii=False),
            )
            return HTMLResponse(html, headers=no_store)

        @app.post('/kremle/verify')
        async def kremle_verify(request: Request):
            try:
                data = await request.json()
            except (ValueError, TypeError):
                return JSONResponse({'error': 'invalid_json'}, status_code=400)
            if not isinstance(data, dict):
                return JSONResponse({'error': 'invalid_json'}, status_code=400)

            token = data.get('token') or request.session.get(TOKEN_KEY, '')
            answers = data.get('answers', {})
            fingerprint = data.get('fingerprint')
            ip = _client_ip(request, trusted_proxies)

            result = await run(engine.verify, token, answers, ip=ip, fingerprint=fingerprint)
            request.session.pop(TOKEN_KEY, None)

            if result['passed']:
                request.session[SESSION_KEY] = build_verification(
                    ip=ip,
                    ua=request.headers.get('user-agent'),
                    ttl=engine.verified_ttl,
                )
                next_url = request.session.pop(NEXT_KEY, '/')
                result['redirect'] = next_url
            else:
                result['redirect'] = None

            return JSONResponse(result)

        @app.get('/kremle/status')
        async def kremle_status(request: Request):
            state = request.session.get(SESSION_KEY)
            return JSONResponse({
                'verified': is_verified(
                    state,
                    ua=request.headers.get('user-agent'),
                    bind_ua=self.bind_ua,
                ),
                'expires_in': remaining_seconds(state),
            })

        @app.post('/kremle/logout')
        async def kremle_logout(request: Request):
            request.session.pop(SESSION_KEY, None)
            request.session.pop(TOKEN_KEY, None)
            request.session.pop(NEXT_KEY, None)
            return JSONResponse({'verified': False})

        @app.get('/kremle/img/{key}')
        async def kremle_image(key: str):
            """Картинка задания из локального кеша (см. ``kremle_detect.images``)."""
            entry = await run(read_image, key, engine.images_cache_dir)
            if entry is None:
                return PlainTextResponse('', status_code=404, headers={'Cache-Control': 'no-store'})
            return Response(
                entry['bytes'],
                media_type=entry['content_type'],
                headers=IMAGE_RESPONSE_HEADERS,
            )

        if enable_ops:
            @app.get('/kremle/health')
            async def kremle_health():
                storage = engine.storage
                payload = await run(
                    health_payload,
                    version=__version__,
                    storage=storage,
                    storage_name=_storage_name(storage),
                    extra={
                        'sample_rate': engine.sample_rate,
                        'policy': dict(engine.policy),
                        'verified_ttl': engine.verified_ttl,
                        'questions_source': engine.questions_source,
                        'questions_images': engine.questions_images,
                        'async_offload': self.async_offload,
                    },
                )
                return JSONResponse(payload, status_code=200 if payload['storage_ok'] else 503)

            @app.get('/kremle/stats')
            async def kremle_stats():
                return JSONResponse(await run(engine.metrics.snapshot))

            @app.get('/kremle/metrics')
            async def kremle_metrics():
                text = await run(engine.metrics.prometheus)
                return PlainTextResponse(text, media_type='text/plain; version=0.0.4; charset=utf-8')

        # SessionMiddleware must be added AFTER kremle_guard so that it ends up as
        # the outermost middleware (Starlette builds the stack in reverse order of
        # registration — last registered = outermost = runs first on incoming requests).
        has_session = any(
            getattr(m, 'cls', None) is not None and
            getattr(m, 'cls').__name__ == 'SessionMiddleware'
            for m in getattr(app, 'user_middleware', [])
        )
        if not has_session:
            if SessionMiddleware is None:
                raise RuntimeError(
                    'Для сессий капчи нужен itsdangerous: '
                    'pip install "kremle-detect[fastapi]" (или itsdangerous)'
                )
            app.add_middleware(SessionMiddleware, secret_key=self.secret)
