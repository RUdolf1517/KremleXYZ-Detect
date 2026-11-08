import React from 'react'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { KremleOverlay } from '../KremleOverlay'

const CHALLENGE = {
  questions: [
    { q: 'Сколько будет 2+2?', opts: ['3', '4', '5', '6'], category: 'math' },
    { q: 'Столица России?', opts: ['Москва', 'Казань'] },
  ],
  token: 'tok-1',
  verify_url: '/kremle/verify',
  sources: [],
  attribution: '',
}

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve({
    ok: status < 400,
    status,
    json: () => Promise.resolve(body),
  } as Response)
}

function mockFetch(handlers: {
  status?: () => Promise<Response>
  challenge?: () => Promise<Response>
  verify?: () => Promise<Response>
} = {}) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation((input: any) => {
    const url = String(input)
    if (url.includes('/status')) {
      return (handlers.status ?? (() => jsonResponse({ verified: false, pending: true })))()
    }
    if (url.includes('/challenge')) return (handlers.challenge ?? (() => jsonResponse(CHALLENGE)))()
    if (url.includes('/verify')) {
      return (handlers.verify ?? (() => jsonResponse({ passed: true, errors: 0, total: 2 })))()
    }
    return jsonResponse({}, 404)
  })
}

function answerAll() {
  fireEvent.click(screen.getByLabelText('4'))
  fireEvent.click(screen.getByLabelText('Москва'))
}

describe('KremleOverlay', () => {
  beforeEach(() => {
    document.body.style.overflow = ''
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('не рисует ничего, если капча не требуется', async () => {
    mockFetch({ status: () => jsonResponse({ verified: true, pending: false }) })
    const { container } = render(<KremleOverlay />)

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled())
    expect(container.querySelector('.kremle-overlay')).toBeNull()
  })

  it('показывает окно поверх, когда сервер сказал pending', async () => {
    mockFetch()
    render(<KremleOverlay />)

    const overlay = await screen.findByRole('dialog')
    expect(overlay).toBeTruthy()
    expect(overlay.getAttribute('aria-modal')).toBe('true')
    // вопросы уже загружены — их видно поверх страницы
    expect(await screen.findByText(/Сколько будет 2\+2\?/)).toBeTruthy()
  })

  it('блокирует прокрутку фона и возвращает её после закрытия', async () => {
    mockFetch({
      verify: () => jsonResponse({ passed: true, errors: 0, total: 2 }),
    })
    const { unmount } = render(<KremleOverlay reloadOnPass={false} />)
    await screen.findByRole('dialog')
    expect(document.body.style.overflow).toBe('hidden')

    unmount()
    expect(document.body.style.overflow).toBe('')
  })

  it('после прохождения закрывается и зовёт onSolved', async () => {
    mockFetch()
    const solved = vi.fn()
    render(<KremleOverlay reloadOnPass={false} onSolved={solved} />)

    await screen.findByRole('dialog')
    await screen.findByText(/Сколько будет 2\+2\?/)
    answerAll()
    fireEvent.click(screen.getByText('[ отправить ]'))

    await waitFor(() => expect(solved).toHaveBeenCalledTimes(1))
    expect(solved.mock.calls[0][0].passed).toBe(true)
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('перезагружает страницу после прохождения, если не отключено', async () => {
    mockFetch()
    const reload = vi.fn()
    const original = window.location
    Object.defineProperty(window, 'location', { configurable: true, value: { ...original, reload } })

    render(<KremleOverlay />)
    await screen.findByRole('dialog')
    await screen.findByText(/Сколько будет 2\+2\?/)
    answerAll()
    fireEvent.click(screen.getByText('[ отправить ]'))

    await waitFor(() => expect(reload).toHaveBeenCalledTimes(1))
    Object.defineProperty(window, 'location', { configurable: true, value: original })
  })

  it('недоступный статус не ломает страницу', async () => {
    mockFetch({ status: () => jsonResponse({}, 503) })
    const onError = vi.fn()
    const { container } = render(<KremleOverlay onError={onError} />)

    await waitFor(() => expect(onError).toHaveBeenCalled())
    expect(container.querySelector('.kremle-overlay')).toBeNull()
  })

  it('управляемый режим: open без проверки статуса', async () => {
    const spy = mockFetch()
    render(<KremleOverlay open checkOnMount={false} />)

    expect(await screen.findByRole('dialog')).toBeTruthy()
    const urls = spy.mock.calls.map((call) => String(call[0]))
    expect(urls.some((url) => url.includes('/status'))).toBe(false)
  })
})
