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
from typing import Optional, Sequence

from ..captcha import CaptchaEngine
from ..detector import detect

SESSION_KEY = 'kremle_ok'
NEXT_KEY = 'kremle_next'


class KremleFastAPI:
    """
    FastAPI-интеграция.

    Добавляет middleware + роуты /kremle/challenge, /kremle/verify, /kremle/status.
    Для сессий использует подписанные куки (itsdangerous через Starlette SessionMiddleware).
    """

    def __init__(
        self,
        app=None,
        categories: Optional[Sequence[str]] = None,
        question_count: int = 15,
        max_errors: int = 3,
        secret: str = 'kremle-default-secret',
        skip_paths: Optional[Sequence[str]] = None,
    ):
        self.engine = CaptchaEngine(
            categories=categories,
            question_count=question_count,
            max_errors=max_errors,
            secret=secret,
        )
        self.skip_paths = list(skip_paths or ['/docs', '/openapi.json', '/redoc'])
        self.secret = secret

        if app is not None:
            self.init_app(app)

    def init_app(self, app) -> None:
        from fastapi import Request
        from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
        from starlette.middleware.sessions import SessionMiddleware

        # Добавляем SessionMiddleware если его ещё нет
        has_session = any(
            getattr(m, 'cls', None).__name__ == 'SessionMiddleware'
            for m in getattr(app, 'user_middleware', [])
            if hasattr(m, 'cls')
        )
        if not has_session:
            app.add_middleware(SessionMiddleware, secret_key=self.secret)

        engine = self.engine
        skip_paths = self.skip_paths
        template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates')

        # ── Middleware ────────────────────────────────────────────────────
        @app.middleware('http')
        async def kremle_guard(request: Request, call_next):
            path = request.url.path

            if (
                path.startswith('/kremle/')
                or any(path.startswith(s) for s in skip_paths)
            ):
                return await call_next(request)

            if request.session.get(SESSION_KEY):
                return await call_next(request)

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
                request.session[NEXT_KEY] = str(request.url)
                return RedirectResponse('/kremle/challenge', status_code=302)

            return await call_next(request)

        # ── Routes ───────────────────────────────────────────────────────
        @app.get('/kremle/challenge', response_class=HTMLResponse)
        async def kremle_challenge(request: Request):
            ch = engine.create_challenge()
            request.session['kremle_token'] = ch.token

            tpl_path = os.path.join(template_dir, 'kremle_captcha.html')
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

            result = engine.verify(token, answers)

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
