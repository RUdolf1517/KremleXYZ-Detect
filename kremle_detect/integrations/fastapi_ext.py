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

import ipaddress
import json
import os
from typing import Callable, List, Optional, Sequence

from ..captcha import CaptchaEngine
from ..detector import detect
from ..storage import BaseStorage

SESSION_KEY = 'kremle_ok'
NEXT_KEY = 'kremle_next'


def _ip_in_whitelist(ip: str, whitelist: list) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in whitelist:
        try:
            if '/' in entry:
                if addr in ipaddress.ip_network(entry, strict=False):
                    return True
            else:
                if addr == ipaddress.ip_address(entry):
                    return True
        except ValueError:
            continue
    return False


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
        )
        self.skip_paths = list(skip_paths or ['/docs', '/openapi.json', '/redoc'])
        self.whitelist = whitelist or []
        self.custom_template = template
        self.secret = secret

        if app is not None:
            self.init_app(app)

    def init_app(self, app) -> None:
        from fastapi import Request
        from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
        from starlette.middleware.sessions import SessionMiddleware

        has_session = any(
            getattr(m, 'cls', None).__name__ == 'SessionMiddleware'
            for m in getattr(app, 'user_middleware', [])
            if hasattr(m, 'cls')
        )
        if not has_session:
            app.add_middleware(SessionMiddleware, secret_key=self.secret)

        engine = self.engine
        skip_paths = self.skip_paths
        whitelist = self.whitelist
        custom_template = self.custom_template
        template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates')

        @app.middleware('http')
        async def kremle_guard(request: Request, call_next):
            path = request.url.path

            if path.startswith('/kremle/') or any(path.startswith(s) for s in skip_paths):
                return await call_next(request)

            if request.session.get(SESSION_KEY):
                return await call_next(request)

            # IP whitelist / blacklist
            ip = request.client.host if request.client else ''
            if whitelist and _ip_in_whitelist(ip, whitelist):
                return await call_next(request)

            if engine.is_blacklisted(ip):
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
                request.session[NEXT_KEY] = str(request.url)
                return RedirectResponse('/kremle/challenge', status_code=302)

            return await call_next(request)

        @app.get('/kremle/challenge', response_class=HTMLResponse)
        async def kremle_challenge(request: Request):
            ch = engine.create_challenge()
            request.session['kremle_token'] = ch.token

            tpl_path = custom_template or os.path.join(template_dir, 'kremle_captcha.html')
            with open(tpl_path, encoding='utf-8') as f:
                html = f.read()

            html = html.replace(
                '{{ questions_json }}',
                json.dumps(ch.to_dict(), ensure_ascii=False),
            )
            return HTMLResponse(html)

        @app.post('/kremle/verify')
        async def kremle_verify(request: Request):
            data = await request.json()
            token = data.get('token') or request.session.get('kremle_token', '')
            answers = data.get('answers', {})
            fingerprint = data.get('fingerprint')
            ip = request.client.host if request.client else ''

            result = engine.verify(token, answers, ip=ip, fingerprint=fingerprint)

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
