import { useCallback, useEffect, useRef, useState } from 'react'
import { collectFingerprint } from './fingerprint'
import type {
  HoneypotValues,
  KremleChallengeData,
  KremleQuestion,
  KremleResult,
  KremleSource,
  UseKremleOptions,
  UseKremleReturn,
} from './types'

function deriveLogoutUrl(verifyUrl: string): string {
  return verifyUrl.replace(/\/verify\/?$/, '/logout')
}

/**
 * Хук капчи: загрузка вопросов, ответы, отправка.
 *
 * Пример:
 *   const { questions, setAnswer, submit, result } = useKremle()
 */
export function useKremle({
  challengeUrl = '/kremle/challenge',
  verifyUrl = '/kremle/verify',
  logoutUrl,
  autoReloadOnExpired = true,
  fingerprint: fingerprintFn,
}: UseKremleOptions = {}): UseKremleReturn {
  const [questions, setQuestions] = useState<KremleQuestion[]>([])
  const [sources, setSources] = useState<KremleSource[]>([])
  const [attribution, setAttribution] = useState<string>('')
  const [token, setToken] = useState<string>('')
  const [answers, setAnswers] = useState<Record<string, number>>({})
  const [loading, setLoading] = useState<boolean>(false)
  const [submitting, setSubmitting] = useState<boolean>(false)
  const [result, setResult] = useState<KremleResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await fetch(challengeUrl, {
        credentials: 'include',
        headers: { Accept: 'application/json' },
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = (await res.json()) as KremleChallengeData
      if (!mounted.current) return
      setQuestions(data.questions ?? [])
      setSources(data.sources ?? [])
      setAttribution(data.attribution ?? '')
      setToken(data.token ?? '')
      setAnswers({})
    } catch (e: unknown) {
      if (!mounted.current) return
      setError(e instanceof Error ? e.message : 'Failed to load challenge')
    } finally {
      if (mounted.current) setLoading(false)
    }
  }, [challengeUrl])

  useEffect(() => {
    void load()
  }, [load])

  const setAnswer = useCallback((questionIndex: number, optionIndex: number) => {
    setAnswers((prev) => ({ ...prev, [String(questionIndex)]: optionIndex }))
  }, [])

  const submit = useCallback(
    async (honeypot: HoneypotValues = {}): Promise<KremleResult | null> => {
      setSubmitting(true)
      setError(null)
      try {
        const fingerprint = (fingerprintFn ?? collectFingerprint)(honeypot)
        const res = await fetch(verifyUrl, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ token, answers, fingerprint }),
        })
        const data = (await res.json()) as KremleResult
        if (!mounted.current) return data
        setResult(data)

        if (data.error === 'invalid_token' && autoReloadOnExpired) {
          // Токен одноразовый и живёт 15 минут — берём новый челлендж
          await load()
        }
        return data
      } catch (e: unknown) {
        if (!mounted.current) return null
        setError(e instanceof Error ? e.message : 'Failed to submit')
        return null
      } finally {
        if (mounted.current) setSubmitting(false)
      }
    },
    [token, answers, verifyUrl, autoReloadOnExpired, fingerprintFn, load],
  )

  const retry = useCallback(async () => {
    const url = logoutUrl ?? deriveLogoutUrl(verifyUrl)
    try {
      await fetch(url, { method: 'POST', credentials: 'include' })
    } catch {
      // logout недоступен — всё равно пробуем новый челлендж
    }
    await load()
  }, [logoutUrl, verifyUrl, load])

  const allAnswered =
    questions.length > 0 && questions.every((_, i) => answers[String(i)] !== undefined)

  return {
    questions,
    sources,
    attribution,
    token,
    answers,
    setAnswer,
    submit,
    reload: load,
    retry,
    loading,
    submitting,
    result,
    error,
    allAnswered,
  }
}
