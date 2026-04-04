import { useCallback, useEffect, useState } from 'react'
import type { KremleQuestion, KremleResult, UseKremleOptions, UseKremleReturn } from './types'

function collectFingerprint() {
  const ua = typeof navigator !== 'undefined' ? navigator.userAgent : ''
  return {
    yaBrands: /YaBrowser/.test(ua),
    yandexApi: typeof window !== 'undefined' && 'yandex' in window,
    honeypot: false,
  }
}

export function useKremle({
  challengeUrl = '/kremle/challenge',
  verifyUrl = '/kremle/verify',
}: UseKremleOptions = {}): UseKremleReturn {
  const [questions, setQuestions] = useState<KremleQuestion[]>([])
  const [token, setToken] = useState<string>('')
  const [answers, setAnswers] = useState<Record<string, number>>({})
  const [loading, setLoading] = useState<boolean>(false)
  const [submitting, setSubmitting] = useState<boolean>(false)
  const [result, setResult] = useState<KremleResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await fetch(challengeUrl, { credentials: 'include' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setQuestions(data.questions ?? [])
      setToken(data.token ?? '')
      setAnswers({})
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load challenge')
    } finally {
      setLoading(false)
    }
  }, [challengeUrl])

  useEffect(() => {
    reload()
  }, [reload])

  const setAnswer = useCallback((questionIndex: number, optionIndex: number) => {
    setAnswers((prev) => ({ ...prev, [String(questionIndex)]: optionIndex }))
  }, [])

  const submit = useCallback(async (): Promise<KremleResult | null> => {
    setSubmitting(true)
    setError(null)
    try {
      const fingerprint = collectFingerprint()
      const res = await fetch(verifyUrl, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, answers, fingerprint }),
      })
      const data: KremleResult = await res.json()
      setResult(data)
      return data
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to submit')
      return null
    } finally {
      setSubmitting(false)
    }
  }, [token, answers, verifyUrl])

  return {
    questions,
    token,
    answers,
    setAnswer,
    submit,
    reload,
    loading,
    submitting,
    result,
    error,
  }
}
