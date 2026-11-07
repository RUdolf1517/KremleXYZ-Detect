# -*- coding: utf-8 -*-
"""
Виджет капчи без React: один ``<script>`` и один ``<div>``.

Сборка виджета живёт в ``kremle-widget/`` (esbuild, ~11 КБ минифицированного
JS). Готовый бандл кладётся в ``kremle_detect/static/widget/`` и уезжает в
wheel, поэтому на стороне пользователя не нужны ни Node, ни сборщик: интеграции
отдают файл своим роутом ``/kremle/widget/kremle-widget.min.js``.

Пример:
    from kremle_detect.widget import widget_snippet

    snippet = widget_snippet()
    # '<div id="kremle"></div>\\n<script src="/kremle/widget/kremle-widget.min.js"></script>...'
"""

from __future__ import annotations

import os
from typing import Optional

#: Каталог со собранными бандлами внутри пакета (попадает в wheel).
STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static', 'widget')

#: Отдаваемые имена файлов: белый список, а не «любой путь в каталоге».
BUNDLES = {
    'kremle-widget.js': 'kremle-widget.js',
    'kremle-widget.min.js': 'kremle-widget.min.js',
    'kremle-widget.mjs': 'kremle-widget.mjs',
}

#: Имя по умолчанию для роутов.
DEFAULT_BUNDLE = 'kremle-widget.min.js'

#: Куда роуты интеграций вешают бандл.
DEFAULT_PREFIX = '/kremle/widget/'

CONTENT_TYPE = 'application/javascript; charset=utf-8'


def bundle_path(name: str = DEFAULT_BUNDLE, static_dir: Optional[str] = None) -> Optional[str]:
    """
    Путь к собранному бандлу или ``None``, если он не собран.

    Имя проверяется по белому списку: ``../`` и прочие радости не проходят.

    Пример:
        bundle_path('kremle-widget.min.js')   # '/.../static/widget/kremle-widget.min.js'
        bundle_path('../../etc/passwd')       # None
    """
    filename = BUNDLES.get(name)
    if filename is None:
        return None
    path = os.path.join(static_dir or STATIC_DIR, filename)
    return path if os.path.isfile(path) else None


def read_bundle(name: str = DEFAULT_BUNDLE, static_dir: Optional[str] = None) -> Optional[bytes]:
    """
    Содержимое бандла (``None`` — не собран).

    Пример:
        data = read_bundle()
        data.startswith(b'var KremleWidget')   # True
    """
    path = bundle_path(name, static_dir)
    if path is None:
        return None
    with open(path, 'rb') as handle:
        return handle.read()


def widget_snippet(
    challenge_url: str = '/kremle/challenge',
    verify_url: str = '/kremle/verify',
    bundle_url: str = DEFAULT_PREFIX + DEFAULT_BUNDLE,
    selector: str = '#kremle',
    title: Optional[str] = None,
    redirect_on_pass: bool = False,
) -> str:
    """
    Готовый HTML: контейнер, скрипт и монтирование.

    Вставляется куда угодно, где отдаётся ваша страница — WordPress, лендинг,
    шаблон Django. Никаких сборок и зависимостей.

    Пример:
        print(widget_snippet(title='[ проверка ]'))
    """
    target = selector.lstrip('#')
    options = [f'challengeUrl: {challenge_url!r}', f'verifyUrl: {verify_url!r}']
    if title:
        options.append(f'title: {title!r}')
    if redirect_on_pass:
        options.append('redirectOnPass: true')
    options_js = '{ ' + ', '.join(options) + ' }'
    return (
        f'<div id="{target}" data-kremle></div>\n'
        f'<script src="{bundle_url}"></script>\n'
        f'<script>KremleWidget.mount("#{target}", {options_js});</script>'
    )


def headers(cache_seconds: int = 86400) -> dict:
    """
    Заголовки ответа с бандлом: кешируем, но не даём угадывать тип.

    Пример:
        headers()['X-Content-Type-Options']   # 'nosniff'
    """
    return {
        'Content-Type': CONTENT_TYPE,
        'Cache-Control': f'public, max-age={cache_seconds}',
        'X-Content-Type-Options': 'nosniff',
    }
