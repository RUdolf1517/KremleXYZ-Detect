# Сниппеты: WordPress, nginx, Docker

> «Не надо переписывать весь дом, чтобы поставить замок на дверь.»

Готовые копипаст-блоки для тех случаев, когда «разверните приложение» — это
слишком много слов.

## WordPress

Капча ставится виджетом: один `<script>` в теме, без плагинов и без сборки.

**1. Откуда берётся капча.** Настоящей проверке нужен бэкенд `kremle-detect` —
обычно он живёт рядом: `kremle-detect serve` на порту 8000 или контейнер
(см. ниже). Если капча должна проверять именно WordPress-пользователей,
проще поставить [Flask/Django/FastAPI](integrations/flask.md) перед сайтом и
пропускать через него PHP — вариант «Nginx + капча перед PHP» ниже.

**2. Разметка в шаблоне темы** (`footer.php` или хук `wp_footer`):

```php
<?php // functions.php — подключаем скрипт и монтируем капчу ?>
<script src="https://captcha.example.ru/kremle/widget/kremle-widget.min.js"></script>
<div id="kremle"></div>
<script>
  KremleWidget.mount('#kremle', {
    challengeUrl: 'https://captcha.example.ru/kremle/challenge',
    verifyUrl: 'https://captcha.example.ru/kremle/verify',
    onPass: function () { window.location.reload(); },
  });
</script>
```

**3. Куки и CORS.** Виджет ходит с `credentials: 'include'` — это значит, что
челлендж и проверка должны быть на **одном** домене с той страницей, где капча,
либо сервер должен слать `Access-Control-Allow-Credentials: true` и конкретный
`Access-Control-Allow-Origin` (не `*`). Самый простой рабочий путь — проксировать
`/kremle/` через nginx на тот же домен (следующий раздел).

**4. Кеш.** Страницы с капчей не кешируйте: `Cache-Control: no-store` уже
отдаётся на роутах капчи, но плагины кеша страниц могут отдать старый HTML.
Страницу капчи исключите из кеша.

## nginx

### Обратный прокси на `kremle-detect`

```nginx
upstream kremle {
    server 127.0.0.1:8000;      # kremle-detect serve
    keepalive 16;
}

server {
    listen 443 ssl http2;
    server_name example.ru;

    # капча и её виджет — на своём домене, CORS не нужен вовсе
    location /kremle/ {
        proxy_pass http://kremle;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        # заголовок нужен, только если прокси доверенный; иначе клиент подделает IP
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 10s;

        # свой HTML-шаблон и виджет можно кешировать, челлендж — нет
        location /kremle/widget/ {
            proxy_pass http://kremle;
            proxy_cache_valid 200 1h;
        }
    }
}
```

На стороне приложения выставьте `trusted_proxies` под адрес nginx, иначе
`X-Forwarded-For` будет проигнорирован (и это правильно):

```python
KremleFlask(app, trusted_proxies=['127.0.0.1'])
```

### Ограничение частоты на краю

```nginx
limit_req_zone $binary_remote_addr zone=kremle_challenge:10m rate=30r/m;

location = /kremle/challenge {
    limit_req zone=kremle_challenge burst=10 nodelay;
    limit_req_status 429;
    proxy_pass http://kremle;
}
```

Двойной лимит (на краю и в приложении) не мешает: оба считают по IP, и 429
клиент получит от того, кто сработал первым.

### Капча перед PHP (WordPress)

```nginx
location / {
    # всё, что не статика, идёт через приложение с капчей
    try_files $uri $uri/ @kremle;

    # статику отдаём сами: зачем ей капча
    location ~* \.(css|js|png|jpg|jpeg|gif|svg|webp|ico|woff2?)$ {
        expires 7d;
        access_log off;
        try_files $uri =404;
    }
}

location @kremle {
    proxy_pass http://kremle;          # kremle-detect serve с policy
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

Такой вариант уместен, когда приложение само решает, кого пускать (monitor →
challenge), и умеет отдавать контент PHP-сайта. Начните с
`KREMLE_DEMO_POLICY=monitor`, посмотрите `/kremle/stats`, потом включайте
`challenge`.

## Docker Compose

```yaml
services:
  kremle:
    image: ghcr.io/rudolf1517/kremle-detect:latest
    ports:
      - "8000:8000"
    environment:
      KREMLE_SECRET: ${KREMLE_SECRET:?задайте свой ключ}
      KREMLE_DEMO_POLICY: monitor          # сначала считаем, потом блокируем
      KREMLE_REDIS_URL: redis://redis:6379/0
      KREMLE_QUESTIONS_SOURCE: own+sdamgia  # своё + портал (2.11+)
      KREMLE_MIXED_RATIO: "0.5"
    volumes:
      - kremle-cache:/data
    depends_on:
      redis:
        condition: service_healthy
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    command: ["redis-server", "--save", "", "--appendonly", "no"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 3

volumes:
  kremle-cache:
```

`docker compose up` в репозитории поднимает демо одной командой
(`docker-compose.yml` в корне), `docker compose pull && docker compose up` —
без сборки, из GHCR.

!!! warning "Кеш вопросов — в томе"
    `/data` монтируется томом: `kremle-detect questions sync` кладёт туда кеш
    «Решу ЕГЭ». Без тома после пересоздания контейнера вопросы придётся качать
    заново.

## systemd

```ini
[Unit]
Description=kremle-detect
After=network.target

[Service]
User=kremle
Environment=KREMLE_SECRET=замените-на-свой
Environment=KREMLE_REDIS_URL=redis://127.0.0.1:6379/0
ExecStart=/opt/kremle/venv/bin/kremle-detect serve --port 8000
Restart=always
RestartSec=3
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/kremle

[Install]
WantedBy=multi-user.target
```

## Что проверить после установки

```bash
curl -s localhost:8000/kremle/health          # status: ok
curl -sI localhost:8000/kremle/challenge | grep -i 'x-frame-options'   # DENY
curl -s localhost:8000/kremle/widget/kremle-widget.min.js | head -c 40 # виджет на месте
```

---

*Дисклеймер: патриотический пафос на этой странице — сатира в жанре
государственнического текста, а не политическая позиция проекта и не
рекомендация блокировать чьи-либо браузеры. Технические утверждения — правда,
их проверяют тесты; идеологические — шутка.*
