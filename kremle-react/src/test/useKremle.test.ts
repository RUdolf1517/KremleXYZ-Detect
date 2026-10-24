import { describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { useKremle } from '../useKremle'

const CHALLENGE = {
  questions: [{ q: 'Q1?', opts: ['a', 'b'] }],
  token: 't1',
  sources: [],
  attribution: '',
}

function jsonResponse(body: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) } as Response)
}

describe('useKremle', () => {
  it('загружает challenge и выставляет вопросы', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => jsonResponse(CHALLENGE))
    const { result } = renderHook(() => useKremle())

    await waitFor(() => expect(result.current.questions).toHaveLength(1))
    expect(result.current.token).toBe('t1')
    expect(result.current.allAnswered).toBe(false)
  })

  it('allAnswered становится true после ответов на все вопросы', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => jsonResponse(CHALLENGE))
    const { result } = renderHook(() => useKremle())
    await waitFor(() => expect(result.current.questions).toHaveLength(1))

    act(() => result.current.setAnswer(0, 1))
    expect(result.current.allAnswered).toBe(true)
    expect(result.current.answers).toEqual({ '0': 1 })
  })

  it('submit возвращает результат сервера', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      if (String(input).includes('/verify')) return jsonResponse({ passed: true, errors: 0, total: 1 })
      return jsonResponse(CHALLENGE)
    })
    const { result } = renderHook(() => useKremle())
    await waitFor(() => expect(result.current.token).toBe('t1'))

    let res: any
    await act(async () => {
      res = await result.current.submit()
    })
    expect(res.passed).toBe(true)
    expect(result.current.result?.passed).toBe(true)
  })

  it('reload очищает ответы', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => jsonResponse(CHALLENGE))
    const { result } = renderHook(() => useKremle())
    await waitFor(() => expect(result.current.questions).toHaveLength(1))
    act(() => result.current.setAnswer(0, 0))

    await act(async () => {
      await result.current.reload()
    })
    expect(result.current.answers).toEqual({})
  })

  it('сетевой сбой загрузки попадает в error', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => Promise.reject(new Error('down')))
    const { result } = renderHook(() => useKremle())
    await waitFor(() => expect(result.current.error).toBe('down'))
  })
})
