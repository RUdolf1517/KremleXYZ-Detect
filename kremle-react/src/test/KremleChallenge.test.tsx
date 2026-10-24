import React from 'react'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { KremleChallenge } from '../KremleChallenge'

const CHALLENGE = {
  questions: [
    { q: 'Сколько будет 2+2?', opts: ['3', '4', '5', '6'], category: 'math' },
    { q: 'Столица России?', opts: ['Москва', 'Казань'] },
  ],
  token: 'tok-1',
  verify_url: '/kremle/verify',
  sources: [{ name: 'РешуЕГЭ', url: 'https://sdamgia.ru/', author: 'Д. Д. Гущин' }],
  attribution: 'Задания: РешуЕГЭ',
}

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve({
    ok: status < 400,
    status,
    json: () => Promise.resolve(body),
  } as Response)
}

function mockFetch(handlers: { challenge?: () => Promise<Response>; verify?: (body: any) => Promise<Response>; logout?: () => Promise<Response> }) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation((input: any, init?: any) => {
    const url = String(input)
    if (url.includes('/challenge')) return (handlers.challenge ?? (() => jsonResponse(CHALLENGE)))()
    if (url.includes('/logout')) return (handlers.logout ?? (() => jsonResponse({ verified: false })))()
    if (url.includes('/verify')) {
      const body = init?.body ? JSON.parse(init.body) : {}
      return (handlers.verify ?? (() => jsonResponse({ passed: true, errors: 0, total: 2 })))(body)
    }
    return jsonResponse({}, 404)
  })
}

function answerAll() {
  fireEvent.click(screen.getByLabelText('4'))
  fireEvent.click(screen.getByLabelText('Москва'))
}

describe('KremleChallenge', () => {
  beforeEach(() => {
    mockFetch({})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('показывает загрузку, затем вопросы', async () => {
    render(<KremleChallenge />)
    expect(screen.getByText('[ загрузка... ]')).toBeTruthy()
    expect(await screen.findByText(/2\+2/)).toBeTruthy()
    expect(screen.getByText(/Столица России\?/)).toBeTruthy()
  })

  it('кнопка отправки заблокирована, пока не отвечены все вопросы', async () => {
    render(<KremleChallenge />)
    const button = await screen.findByRole('button', { name: '[ отправить ]' })
    expect((button as HTMLButtonElement).disabled).toBe(true)
    answerAll()
    expect((button as HTMLButtonElement).disabled).toBe(false)
  })

  it('отправляет ответы и фингерпринт, вызывает onPass', async () => {
    const onPass = vi.fn()
    let sent: any = null
    mockFetch({
      verify: (body) => {
        sent = body
        return jsonResponse({ passed: true, errors: 0, total: 2 })
      },
    })

    render(<KremleChallenge onPass={onPass} />)
    await screen.findByText(/2\+2/)
    answerAll()
    fireEvent.click(screen.getByRole('button', { name: '[ отправить ]' }))

    await waitFor(() => expect(onPass).toHaveBeenCalledTimes(1))
    expect(sent.token).toBe('tok-1')
    expect(sent.answers).toEqual({ '0': 1, '1': 0 })
    expect(sent.fingerprint).toMatchObject({ honeypot: false })
  })

  it('honeypot: заполненные скрытые поля уходят в fingerprint', async () => {
    let sent: any = null
    mockFetch({
      verify: (body) => {
        sent = body
        return jsonResponse({ passed: false, errors: 2, total: 2 })
      },
    })

    const { container } = render(<KremleChallenge />)
    await screen.findByText(/2\+2/)
    answerAll()

    const honeypot = container.querySelector('input[name="kremle_name"]') as HTMLInputElement
    expect(honeypot).toBeTruthy()
    honeypot.value = 'bot'

    fireEvent.click(screen.getByRole('button', { name: '[ отправить ]' }))
    await waitFor(() => expect(sent).not.toBeNull())
    expect(sent.fingerprint.honeypot).toBe(true)
  })

  it('показывает провал и вызывает onFail', async () => {
    const onFail = vi.fn()
    mockFetch({
      verify: () => jsonResponse({ passed: false, errors: 2, total: 2 }),
    })

    render(<KremleChallenge onFail={onFail} />)
    await screen.findByText(/2\+2/)
    answerAll()
    fireEvent.click(screen.getByRole('button', { name: '[ отправить ]' }))

    await waitFor(() => expect(onFail).toHaveBeenCalledTimes(1))
    expect(screen.getByText(/провал — ошибок: 2\/2/)).toBeTruthy()
  })

  it('для rate_limited показывает понятный текст, а не «ошибок -1 из 0»', async () => {
    mockFetch({
      verify: () => jsonResponse({ passed: false, errors: -1, total: 0, error: 'rate_limited' }),
    })

    render(<KremleChallenge />)
    await screen.findByText(/2\+2/)
    answerAll()
    fireEvent.click(screen.getByRole('button', { name: '[ отправить ]' }))

    expect(await screen.findByText(/слишком много попыток/)).toBeTruthy()
  })

  it('истёкший токен автоматически перезапрашивает челлендж', async () => {
    const challenge = vi.fn(() => jsonResponse(CHALLENGE))
    mockFetch({
      challenge,
      verify: () => jsonResponse({ passed: false, errors: -1, total: 0, error: 'invalid_token' }),
    })

    render(<KremleChallenge />)
    await screen.findByText(/2\+2/)
    answerAll()
    fireEvent.click(screen.getByRole('button', { name: '[ отправить ]' }))

    await waitFor(() => expect(challenge).toHaveBeenCalledTimes(2))
  })

  it('кнопка «попробовать снова» дергает logout и новый челлендж', async () => {
    const logout = vi.fn(() => jsonResponse({ verified: false }))
    const challenge = vi.fn(() => jsonResponse(CHALLENGE))
    mockFetch({
      challenge,
      logout,
      verify: () => jsonResponse({ passed: false, errors: 2, total: 2 }),
    })

    render(<KremleChallenge />)
    await screen.findByText(/2\+2/)
    answerAll()
    fireEvent.click(screen.getByRole('button', { name: '[ отправить ]' }))
    const retry = await screen.findByRole('button', { name: '[ попробовать снова ]' })
    fireEvent.click(retry)

    await waitFor(() => expect(logout).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(challenge).toHaveBeenCalledTimes(2))
  })

  it('показывает атрибуцию источника вопросов', async () => {
    render(<KremleChallenge />)
    const link = await screen.findByRole('link', { name: 'РешуЕГЭ' })
    expect(link.getAttribute('href')).toBe('https://sdamgia.ru/')
    // текст разбит на «Задания: » + ссылку, поэтому проверяем контейнер
    expect(link.parentElement?.textContent).toContain('Задания: РешуЕГЭ')
  })

  it('атрибуцию можно отключить', async () => {
    render(<KremleChallenge showAttribution={false} />)
    await screen.findByText(/2\+2/)
    expect(screen.queryByRole('link', { name: 'РешуЕГЭ' })).toBeNull()
  })

  it('сетевая ошибка загрузки показывается и уходит в onError', async () => {
    const onError = vi.fn()
    mockFetch({ challenge: () => Promise.reject(new Error('offline')) })

    render(<KremleChallenge onError={onError} />)
    await waitFor(() => expect(onError).toHaveBeenCalled())
    expect(screen.getByRole('alert').textContent).toContain('offline')
  })
})
