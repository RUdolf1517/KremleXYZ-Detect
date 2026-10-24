# -*- coding: utf-8 -*-
"""
Демо-приложение: посмотреть kremle-detect вживую за одну команду.

    pip install "kremle-detect[demo]"
    kremle-detect serve
    # → http://localhost:8000

Что показывает:
    /         обычная страница (для не-Яндекс браузеров)
    /api/me   JSON-эндпоинт: сюда fetch-клиент получает 403 + captcha_required
    /stats    живая страница со счётчиками (/kremle/stats), автообновление
    /shadow   тот же сайт, но политика monitor: ничего не блокируется

Переменные окружения:
    KREMLE_DEMO_POLICY=monitor   — полный shadow-режим (ничего не блокировать)
    KREMLE_DEMO_PORT=8000
    KREMLE_REDIS_URL=redis://... — хранилище вместо MemoryStorage
"""

from __future__ import annotations

import os
from typing import Optional


def build_app(policy: Optional[dict] = None):
    """
    Собирает демо-приложение FastAPI.

    Пример:
        app = build_app()                       # блокирующая политика
        app = build_app({'yandex_browser': 'monitor'})   # shadow
    """
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse, JSONResponse

    from .integrations.fastapi_ext import KremleFastAPI

    app = FastAPI(title='kremle-detect demo')

    storage = None
    redis_url = os.environ.get('KREMLE_REDIS_URL')
    if redis_url:
        from .storage import RedisStorage
        storage = RedisStorage(url=redis_url)

    kremle = KremleFastAPI(
        app,
        secret=os.environ.get('KREMLE_SECRET', 'demo-secret-not-for-production'),
        storage=storage,
        categories=['math', 'physics'],
        question_count=3,
        max_errors=1,
        policy=policy,
        verified_ttl=300,
        # демо не должно упираться в лимит выдачи при нагрузочном смоуке
        challenge_rate_limit=1000,
        questions_source=os.environ.get('KREMLE_QUESTIONS_SOURCE', 'auto'),
    )

    @app.get('/', response_class=HTMLResponse)
    async def index():
        return _INDEX_HTML

    @app.get('/api/me')
    async def me():
        return JSONResponse({'ok': True, 'user': 'not-a-yandex-browser'})

    @app.get('/stats', response_class=HTMLResponse)
    async def stats_page():
        return _STATS_HTML

    app.state.kremle = kremle
    return app


def main(host: str = '0.0.0.0', port: Optional[int] = None) -> None:
    """Запуск демо через uvicorn (нужен ``kremle-detect[demo]``)."""
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            'Для демо нужен uvicorn: pip install "kremle-detect[demo]"'
        ) from exc

    mode = os.environ.get('KREMLE_DEMO_POLICY', '').lower()
    policy = None
    if mode == 'monitor':
        policy = {
            'yandex_bot': 'monitor',
            'yandex_browser': 'monitor',
            'yandex_client_hints': 'monitor',
            'yandex_referrer': 'monitor',
        }

    app = build_app(policy)
    port = port or int(os.environ.get('KREMLE_DEMO_PORT', '8000'))

    banner = 'shadow (ничего не блокируется)' if policy else 'challenge (Яндекс — капча)'
    print(f'kremle-detect demo → http://localhost:{port}  [{banner}]')
    uvicorn.run(app, host=host, port=port, log_level='info')


_INDEX_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>kremle-detect demo</title>
<style>
  body { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
         background: #0a0a0a; color: #eee; margin: 0; padding: 3rem 1.5rem; }
  main { max-width: 720px; margin: 0 auto; }
  h1 { font-size: 1.5rem; letter-spacing: .05em; }
  a { color: #8ab4ff; }
  code { background: #171717; padding: .15rem .35rem; border-radius: 3px; }
  .box { border: 1px solid #2a2a2a; padding: 1rem 1.25rem; margin: 1.25rem 0; }
  .muted { color: #888; font-size: .9rem; }
  button { font: inherit; background: #171717; color: #eee;
           border: 1px solid #333; padding: .4rem .8rem; cursor: pointer; }
  pre { white-space: pre-wrap; word-break: break-word; color: #9ae6b4; }
</style>
</head>
<body>
<main>
  <h1>[ kremle-detect demo ]</h1>
  <p class="muted">Фильтр по браузеру: Яндекс Браузер, Яндекс-боты и переходы
     с Яндекса получают капчу с вопросами ЕГЭ. Остальные проходят сразу.</p>

  <div class="box">
    <p><b>1. Проверить себя.</b> Откройте <a href="/api/me">/api/me</a> — это JSON-эндпоинт.
       Из Яндекс Браузера придёт <code>403 {"error": "captcha_required"}</code>,
       а не HTML-страница капчи.</p>
    <p><b>2. Посмотреть счётчики.</b> <a href="/stats">/stats</a> — живая страница
       над <code>/kremle/stats</code>.</p>
    <p><b>3. Сырой JSON.</b> <a href="/kremle/stats">/kremle/stats</a> ·
       <a href="/kremle/health">/kremle/health</a> ·
       <a href="/kremle/metrics">/kremle/metrics</a></p>
  </div>

  <div class="box">
    <p><b>Shadow-режим.</b> Перезапустите демо с
      <code>KREMLE_DEMO_POLICY=monitor kremle-detect serve</code> —
      ничего не блокируется, но всё считается (события <code>shadow</code>).</p>
    <button id="ping">Сделать fetch на /api/me</button>
    <pre id="out">—</pre>
  </div>

  <p class="muted">Сгенерировано kremle-detect. Это демо, а не продакшн-конфиг:
     секрет задан в коде, хранилище — память процесса.</p>
</main>
<script>
  document.getElementById('ping').onclick = async function () {
    var out = document.getElementById('out');
    try {
      var r = await fetch('/api/me', {headers: {'Accept': 'application/json'}});
      out.textContent = r.status + ' ' + JSON.stringify(await r.json());
    } catch (e) {
      out.textContent = 'ошибка: ' + e;
    }
  };
</script>
</body>
</html>
"""

_STATS_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>kremle-detect — статистика</title>
<style>
  body { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
         background: #0a0a0a; color: #eee; margin: 0; padding: 3rem 1.5rem; }
  main { max-width: 760px; margin: 0 auto; }
  h1 { font-size: 1.25rem; letter-spacing: .05em; }
  table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
  td { border-bottom: 1px solid #1e1e1e; padding: .35rem .5rem; }
  td:last-child { text-align: right; color: #9ae6b4; }
  .muted { color: #888; font-size: .85rem; }
  a { color: #8ab4ff; }
</style>
</head>
<body>
<main>
  <h1>[ kremle-detect — статистика ]</h1>
  <p class="muted">Обновляется каждые 3 секунды. Это тот же JSON, что отдаёт
     <a href="/kremle/stats">/kremle/stats</a>.</p>
  <table id="t"></table>
  <p class="muted" id="ts"></p>
</main>
<script>
function row(label, value) {
  var tr = document.createElement('tr');
  var a = document.createElement('td');
  a.textContent = label;
  var b = document.createElement('td');
  b.textContent = value;
  tr.appendChild(a); tr.appendChild(b);
  return tr;
}
function flat(prefix, obj, acc) {
  Object.keys(obj).forEach(function (k) {
    var v = obj[k];
    var name = prefix ? prefix + '.' + k : k;
    if (v && typeof v === 'object') { flat(name, v, acc); }
    else { acc.push([name, v]); }
  });
  return acc;
}
async function refresh() {
  try {
    var r = await fetch('/kremle/stats', {headers: {'Accept': 'application/json'}});
    var data = await r.json();
    var table = document.getElementById('t');
    table.innerHTML = '';
    flat('', data, []).forEach(function (pair) {
      table.appendChild(row(pair[0], String(pair[1])));
    });
    document.getElementById('ts').textContent =
      'обновлено: ' + new Date().toLocaleTimeString();
  } catch (e) {
    document.getElementById('ts').textContent = 'ошибка: ' + e;
  }
}
refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>
"""
