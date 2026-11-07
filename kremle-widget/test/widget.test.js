import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { autoMount, collectFingerprint, createWidget, mount, resultMessage } from '../src/index.js'
import { createServer } from './server.js'

const tick = () => new Promise((resolve) => setTimeout(resolve, 0))

let host
let widgets = []

function setup(options = {}) {
  host = document.createElement('div')
  document.body.appendChild(host)
  const server = options.server || createServer(options.serverOptions)
  const widget = mount(host, { fetch: server.fetchImpl, ...options.widgetOptions })
  widgets.push(widget)
  return { widget, server, host }
}

beforeEach(() => {
  document.body.innerHTML = ''
})

afterEach(() => {
  widgets.forEach((widget) => widget.destroy())
  widgets = []
  vi.restoreAllMocks()
})

describe('отрисовка', () => {
  it('рисует вопросы и варианты после загрузки', async () => {
    const { host } = setup()
    await tick()

    const labels = host.querySelectorAll('label')
    expect(labels.length).toBe(8) // 2 вопроса × 4 варианта
    expect(host.textContent).toContain('Производная x² равна')
    expect(host.querySelector('.kremle-submit')).toBeTruthy()
  })

  it('текст вопроса не превращается в HTML', async () => {
    const server = createServer({
      questions: [
        {
          q: '<img src=x onerror=alert(1)>',
          opts: ['<b>жирный</b>', 'обычный', 'третий', 'четвёртый'],
        },
      ],
      verifyAnswers: { 0: 1 },
    })
    const { host } = setup({ server })
    await tick()

    expect(host.querySelector('img')).toBeNull()
    expect(host.querySelector('b')).toBeNull()
    expect(host.textContent).toContain('<img src=x onerror=alert(1)>')
    expect(host.textContent).toContain('<b>жирный</b>')
  })

  it('показывает ошибку и кнопку повтора, если челлендж не пришёл', async () => {
    const { host } = setup({ serverOptions: { failOn: 'challenge' }, widgetOptions: { onError: () => {} } })
    await tick()

    expect(host.querySelector('.kremle-result')).toBeNull()
    expect(host.textContent).toContain('HTTP 500')
    expect(host.querySelector('button').textContent).toBe('начать заново')
  })
})

describe('протокол', () => {
  it('проходит капчу: answers + token + fingerprint уходят на сервер', async () => {
    const onPass = vi.fn()
    const { host, server } = setup({ widgetOptions: { onPass } })
    await tick()

    host.querySelectorAll('input[type=radio]')[0].click()
    host.querySelectorAll('input[type=radio]')[4].click()
    host.querySelector('.kremle-submit').click()
    await tick()

    expect(server.calls.verify).toHaveLength(1)
    const body = server.calls.verify[0]
    expect(body.token).toBe('token-1')
    expect(body.answers).toEqual({ 0: 0, 1: 0 })
    expect(Object.keys(body.fingerprint).sort()).toEqual([
      'honeypot',
      'timezone',
      'webdriver',
      'yaBrands',
      'yandexApi',
    ])
    expect(onPass).toHaveBeenCalledTimes(1)
    expect(host.querySelector('.kremle-result').textContent).toContain('пройдено')
  })

  it('не отправляет неполные ответы', async () => {
    const { host, server } = setup()
    await tick()

    host.querySelectorAll('input[type=radio]')[0].click()
    host.querySelector('.kremle-submit').click()
    await tick()

    expect(server.calls.verify).toHaveLength(0)
    expect(host.textContent).toContain('ответьте на все вопросы')
  })

  it('провал показывает порог с сервера, а не total/2', async () => {
    const onFail = vi.fn()
    const { host } = setup({
      serverOptions: { maxErrors: 1, verifyAnswers: { 0: 3, 1: 3 } },
      widgetOptions: { onFail },
    })
    await tick()

    host.querySelectorAll('input[type=radio]')[0].click()
    host.querySelectorAll('input[type=radio]')[4].click()
    host.querySelector('.kremle-submit').click()
    await tick()

    expect(onFail).toHaveBeenCalledTimes(1)
    expect(host.querySelector('.kremle-result').textContent).toBe(
      'провал — ошибок: 2 из 1 допустимых',
    )
  })

  it('истёкший токен — берём новый челлендж автоматически', async () => {
    const server = createServer()
    const original = server.fetchImpl
    server.fetchImpl = async (url, init) => {
      if (String(url).endsWith('/verify')) {
        return { ok: true, status: 200, json: async () => ({ passed: false, error: 'invalid_token' }) }
      }
      return original(url, init)
    }
    const { host } = setup({ server })
    await tick()

    host.querySelectorAll('input[type=radio]')[0].click()
    host.querySelectorAll('input[type=radio]')[4].click()
    host.querySelector('.kremle-submit').click()
    await tick()

    expect(server.calls.challenge).toBe(2)
  })

  it('retry сначала сбрасывает сессию, потом берёт новый челлендж', async () => {
    const { widget, server } = setup()
    await tick()

    server.calls.logout = 0
    await widget.retry()

    expect(server.calls.logout).toBe(1)
    expect(server.calls.challenge).toBe(2)
  })

  it('пропускает редирект после успеха, если просили', async () => {
    const assign = vi.fn()
    vi.stubGlobal('location', { assign })
    const { host } = setup({ widgetOptions: { redirectOnPass: true } })
    await tick()

    host.querySelectorAll('input[type=radio]')[0].click()
    host.querySelectorAll('input[type=radio]')[4].click()
    host.querySelector('.kremle-submit').click()
    await tick()

    expect(assign).toHaveBeenCalledWith('/secret')
  })
})

describe('honeypot', () => {
  it('заполненные скрытые поля дают honeypot=true', async () => {
    const { host, server } = setup()
    await tick()

    host.querySelector('input[name=kremle_name]').value = 'bot'
    host.querySelectorAll('input[type=radio]')[0].click()
    host.querySelectorAll('input[type=radio]')[4].click()
    host.querySelector('.kremle-submit').click()
    await tick()

    expect(server.calls.verify[0].fingerprint.honeypot).toBe(true)
  })
})

describe('фингерпринт', () => {
  it('пять полей, без лишнего', () => {
    const fp = collectFingerprint()
    expect(Object.keys(fp).sort()).toEqual([
      'honeypot',
      'timezone',
      'webdriver',
      'yaBrands',
      'yandexApi',
    ])
  })

  it('ловит Яндекс Браузер в UA', () => {
    vi.stubGlobal('navigator', {
      userAgent: 'Mozilla/5.0 YaBrowser/24.1 Safari/537.36',
      webdriver: false,
    })
    expect(collectFingerprint().yaBrands).toBe(true)
  })

  it('ловит userAgentData.brands и webdriver', () => {
    vi.stubGlobal('navigator', {
      userAgent: 'Mozilla/5.0 Chrome/120',
      userAgentData: { brands: [{ brand: 'Chromium' }, { brand: 'YaBrowser' }] },
      webdriver: true,
    })
    const fp = collectFingerprint()
    expect(fp.yaBrands).toBe(true)
    expect(fp.webdriver).toBe(true)
  })

  it('ловит window.yandex и часовой пояс', () => {
    vi.stubGlobal('navigator', { userAgent: 'Mozilla/5.0 Chrome/120' })
    globalThis.yandex = {}
    const fp = collectFingerprint()
    expect(fp.yandexApi).toBe(true)
    expect(typeof fp.timezone).toBe('string')
    delete globalThis.yandex
  })
})

describe('публичный API', () => {
  it('mount монтирует в переданный элемент', async () => {
    const { host } = setup()
    await tick()
    expect(host.querySelector('.kremle-widget')).toBeTruthy()
  })

  it('createWidget бросает понятную ошибку на пустом селекторе', () => {
    expect(() => createWidget('#нет-такого')).toThrow(/не найден элемент/)
  })

  it('autoMount читает data-атрибуты', async () => {
    const server = createServer()
    document.body.innerHTML =
      '<div data-kremle data-challenge-url="/kremle/challenge" ' +
      'data-verify-url="/kremle/verify" data-title="[ стоп ]"></div>'
    const created = autoMount(document, { fetch: server.fetchImpl })
    widgets.push(...created)
    await tick()

    expect(created).toHaveLength(1)
    expect(document.querySelector('.kremle-widget h2').textContent).toBe('[ стоп ]')
  })

  it('destroy убирает разметку', async () => {
    const { widget, host } = setup()
    await tick()
    widget.destroy()
    expect(host.querySelector('.kremle-widget')).toBeNull()
  })

  it('resultMessage говорит человеческим языком', () => {
    expect(resultMessage({ passed: true, errors: 0, total: 3 })).toBe('пройдено — ошибок: 0/3')
    expect(resultMessage({ passed: false, errors: 3, total: 3, max_errors: 1 })).toBe(
      'провал — ошибок: 3 из 1 допустимых',
    )
    expect(resultMessage({ passed: false, error: 'rate_limited' })).toContain('слишком много')
    expect(resultMessage({ passed: false, error: 'invalid_token' })).toContain('устарела')
  })
})
