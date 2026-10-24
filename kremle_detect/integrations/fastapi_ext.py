# -*- coding: utf-8 -*-
"""
FastAPI / Starlette интеграция KremleDetect.

Использование:
    from fastapi import FastAPI
    from kremle_detect.integrations.fastapi_ext import KremleFastAPI

    app = FastAPI()
    kremle = KremleFastAPI(
        app,
        categories=['math', 'physics'],
        question_count=10,
        secret='your-secret',
    )
"""

from __future__ import annotations

import json
import os
from typing import Callable, List, Optional, Sequence

from ..captcha import CaptchaEngine
from ..detector import detect
from ..ip import client_ip, ip_matches
from ..storage import BaseStorage

# FastAPI/Starlette are optional dependencies but this file is only imported
# when they are available.  Module-level imports are required so that FastAPI
# can resolve type annotations via func.__globals__ when registering routes
# that are defined inside init_app() closures.
try:
    from fastapi import Request
    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
    from starlette.middleware.sessions import SessionMiddleware
except ImportError:
    pass  # will fail loudly at runtime if user calls init_app without fastapi

SESSION_KEY = 'kremle_ok'
NEXT_KEY = 'kremle_next'


def _ip_in_whitelist(ip: str, whitelist: list) -> bool:
    return ip_matches(ip, whitelist)


def _client_ip(request, trusted_proxies=()) -> str:
    """IP клиента; X-Forwarded-For учитывается только от доверенных прокси."""
    peer = request.client.host if request.client else ''
    return client_ip(peer, request.headers.get('x-forwarded-for', ''), trusted_proxies)


class KremleFastAPI:
    """
    FastAPI-интеграция.

    Добавляет middleware + роуты /kremle/challenge, /kremle/verify, /kremle/status.
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
        )
        self.skip_paths = list(skip_paths or ['/docs', '/openapi.json', '/redoc'])
        self.whitelist = whitelist or []
        self.custom_template = template
        self.secret = secret
        self.headless = headless
        self.trusted_proxies = list(trusted_proxies or [])

        if app is not None:
            self.init_app(app)

    def init_app(self, app) -> None:
        engine = self.engine
        skip_paths = self.skip_paths
        whitelist = self.whitelist
        custom_template = self.custom_template
        headless = self.headless
        trusted_proxies = self.trusted_proxies
        template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates')

        @app.middleware('http')
        async def kremle_guard(request: Request, call_next):
            path = request.url.path

            if path.startswith('/kremle/') or any(path.startswith(s) for s in skip_paths):
                return await call_next(request)

            if request.session.get(SESSION_KEY):
                return await call_next(request)

            # IP whitelist / blacklist (тот же резолвер, что и в /kremle/verify)
            ip = _client_ip(request, trusted_proxies)
            if whitelist and _ip_in_whitelist(ip, whitelist):
                return await call_next(request)
            if engine.is_whitelisted(ip):
                return await call_next(request)

            if engine.is_blacklisted(ip):
                if headless:
                    return JSONResponse(
                        {'error': 'captcha_required', 'reason': 'blacklisted', 'challenge_url': '/kremle/challenge'},
                        status_code=403,
                    )
                return RedirectResponse('/kremle/challenge', status_code=302)

            headers = {
                'User-Agent': request.headers.get('user-agent', ''),
                'Referer': request.headers.get('referer', ''),
                'Sec-CH-UA': request.headers.get('sec-ch-ua', ''),
                'Sec-CH-UA-Full-Version-List': request.headers.get(
                    'sec-ch-ua-full-version-list', ''
                ),
            }
            result = detect(headers)
            if result:
                engine.notify_detect(result, ip=ip)
                if headless:
                    return JSONResponse(
                        {'error': 'captcha_required', 'reason': result.reason, 'challenge_url': '/kremle/challenge'},
                        status_code=403,
                    )
                request.session[NEXT_KEY] = str(request.url)
                return RedirectResponse('/kremle/challenge', status_code=302)

            return await call_next(request)

        @app.get('/kremle/challenge', response_class=HTMLResponse)
        async def kremle_challenge(request: Request):
            ip = _client_ip(request, trusted_proxies)
            if engine.check_challenge_limit(ip):
                return JSONResponse(
                    {'error': 'too_many_requests'},
                    status_code=429,
                    headers={'Cache-Control': 'no-store'},
                )
            engine.track_challenge(ip)

            ch = engine.create_challenge()
            request.session['kremle_token'] = ch.token

            verify_url = str(request.url_for('kremle_verify'))
            no_store = {'Cache-Control': 'no-store, no-cache, must-revalidate', 'Pragma': 'no-cache'}

            if headless:
                return JSONResponse(ch.to_dict(verify_url=verify_url), headers=no_store)

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
                json.dumps(ch.to_dict(verify_url=verify_url), ensure_ascii=False),
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

            token = data.get('token') or request.session.get('kremle_token', '')
            answers = data.get('answers', {})
            fingerprint = data.get('fingerprint')
            ip = _client_ip(request, trusted_proxies)

            result = engine.verify(token, answers, ip=ip, fingerprint=fingerprint)
            request.session.pop('kremle_token', None)

            if result['passed']:
                request.session[SESSION_KEY] = True
                next_url = request.session.pop(NEXT_KEY, '/')
                result['redirect'] = next_url
            else:
                result['redirect'] = None

            return JSONResponse(result)

        @app.get('/kremle/status')
        async def kremle_status(request: Request):
            return JSONResponse({
                'verified': bool(request.session.get(SESSION_KEY))
            })

        # SessionMiddleware must be added AFTER kremle_guard so that it ends up as
        # the outermost middleware (Starlette builds the stack in reverse order of
        # registration — last registered = outermost = runs first on incoming requests).
        has_session = any(
            getattr(m, 'cls', None) is not None and
            getattr(m, 'cls').__name__ == 'SessionMiddleware'
            for m in getattr(app, 'user_middleware', [])
        )
        if not has_session:
            app.add_middleware(SessionMiddleware, secret_key=self.secret)
