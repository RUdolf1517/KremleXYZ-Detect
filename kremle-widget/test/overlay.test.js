import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { autoGuardOverlay, guardOverlay } from '../src/index.js'
import { createServer } from './server.js'

const tick = () => new Promise((resolve) => setTimeout(resolve, 0))
// виджет грузит вопросы своим промисом — ждём пару оборотов очереди
const flush = async () => {
  for (let i = 0; i < 5; i += 1) await tick()
}

let controllers = []

function setup(options = {}, serverOptions = {}) {
  const server = createServer(serverOptions)
  const controller = guardOverlay({
    fetch: server.fetchImpl,
    autoCheck: false,
    reloadOnPass: false,
    ...options,
  })
  controllers.push(controller)
  return { controller, server }
}

beforeEach(() => {
  document.body.innerHTML = ''
  controllers = []
})

afterEach(() => {
  controllers.forEach((controller) => controller.destroy())
  vi.restoreAllMocks()
})

describe('окно поверх страницы', () => {
  it('не показывается, если капча не требуется', async () => {
    const { controller } = setup()
    const data = await controller.check()

    expect(data.pending).toBe(false)
    expect(document.querySelector('.kremle-overlay')).toBeNull()
    expect(controller.getState().open).toBe(false)
  })

  it('показывается, когда сервер сказал pending', async () => {
    const { controller } = setup({}, { pending: true })
    await controller.check()
    await flush()

    const overlay = document.querySelector('.kremle-overlay')
    expect(overlay).toBeTruthy()
    expect(overlay.querySelector('.kremle-overlay-card')).toBeTruthy()
    expect(controller.getState().reason).toBe('yandex_referrer')
    // вопросы уже подгружены из /kremle/challenge
    expect(overlay.querySelectorAll('label').length).toBe(8)
  })

  it('окно — диалог: role, aria-modal и фокус внутри', async () => {
    const { controller } = setup({}, { pending: true })
    await controller.check()
    await flush()

    const card = document.querySelector('.kremle-overlay-card')
    expect(card.getAttribute('role')).toBe('dialog')
    expect(card.getAttribute('aria-modal')).toBe('true')
    expect(card.getAttribute('aria-label')).toBe('[ проверка ]')
    expect(card.contains(document.activeElement)).toBe(true)
  })

  it('блокирует прокрутку фона и возвращает её обратно', async () => {
    document.body.style.overflow = 'scroll'
    const { controller } = setup({}, { pending: true })
    await controller.check()
    expect(document.body.style.overflow).toBe('hidden')

    controller.close()
    expect(document.body.style.overflow).toBe('scroll')
    expect(document.querySelector('.kremle-overlay')).toBeNull()
  })

  it('клик по фону не закрывает окно', async () => {
    const { controller } = setup({}, { pending: true })
    await controller.check()
    const overlay = document.querySelector('.kremle-overlay')
    overlay.click()
    expect(document.querySelector('.kremle-overlay')).toBeTruthy()
  })

  it('после прохождения окно закрывается и зовёт onSolved', async () => {
    const solved = vi.fn()
    const { controller, server } = setup({ onSolved: solved }, { pending: true })
    await controller.check()
    await flush()

    // правильные ответы знает только сервер: в тесте они заданы verifyAnswers
    document.querySelectorAll('input[type=radio]').forEach((input) => {
      if (input.value === '0') {
        input.checked = true
        input.dispatchEvent(new Event('change'))
      }
    })
    await flush()

    const overlay = document.querySelector('.kremle-overlay')
    overlay.querySelector('.kremle-submit').click()
    await flush()

    expect(server.calls.verify.length).toBe(1)
    expect(solved).toHaveBeenCalledTimes(1)
    expect(solved.mock.calls[0][0].passed).toBe(true)
    expect(document.querySelector('.kremle-overlay')).toBeNull()
    expect(controller.getState().solved).toBe(true)
  })

  it('после прохождения перезагружает страницу, если не отключено', async () => {
    const reload = vi.fn()
    const original = window.location
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...original, reload },
    })
    const { controller } = setup({ reloadOnPass: true }, { pending: true })
    await controller.check()
    await flush()

    document.querySelectorAll('input[type=radio]').forEach((input) => {
      if (input.value === '0') {
        input.checked = true
        input.dispatchEvent(new Event('change'))
      }
    })
    await flush()
    document.querySelector('.kremle-overlay .kremle-submit').click()
    await flush()

    expect(reload).toHaveBeenCalledTimes(1)
    Object.defineProperty(window, 'location', { configurable: true, value: original })
  })

  it('недоступный статус не ломает страницу и не открывает окно', async () => {
    const onError = vi.fn()
    const controller = guardOverlay({
      autoCheck: false,
      onError,
      fetch: async () => ({ ok: false, status: 503, json: async () => ({}) }),
    })
    controllers.push(controller)

    const data = await controller.check()
    expect(data).toBeNull()
    expect(onError).toHaveBeenCalled()
    expect(document.querySelector('.kremle-overlay')).toBeNull()
  })

  it('destroy убирает окно и больше не открывает его', async () => {
    const { controller } = setup({}, { pending: true })
    await controller.check()
    controller.destroy()
    expect(document.querySelector('.kremle-overlay')).toBeNull()

    controller.open()
    expect(document.querySelector('.kremle-overlay')).toBeNull()
  })
})

describe('автоподключение', () => {
  it('без документа ничего не создаёт (серверный рендер, импорт в Node)', () => {
    expect(autoGuardOverlay(null)).toBeNull()
  })

  it('открывает окно сразу, если статус уже pending', async () => {
    const server = createServer({ pending: true })
    const controller = autoGuardOverlay(document, { fetch: server.fetchImpl, reloadOnPass: false })
    controllers.push(controller)
    await flush()

    expect(server.calls.status).toBe(1)
    expect(document.querySelector('.kremle-overlay')).toBeTruthy()
  })
})
