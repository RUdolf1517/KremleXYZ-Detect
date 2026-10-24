import type { CSSProperties } from 'react'
import type { HoneypotValues, KremleFingerprint } from './fingerprint'

/** Источник вопроса (атрибуция, например «РешуЕГЭ»). */
export interface KremleSource {
  name: string
  url: string
  author?: string
}

export interface KremleQuestion {
  q: string
  opts: string[]
  category?: string
  source?: KremleSource
  problem_id?: string
}

export interface KremleResult {
  passed: boolean
  errors: number
  total: number
  redirect?: string | null
  /** `invalid_token` | `rate_limited` | `blacklisted` | `invalid_answers` | `blocked` */
  error?: string
  /** Действие политики, если сервер его прислал */
  action?: string
}

/** Ответ GET /kremle/challenge */
export interface KremleChallengeData {
  questions: KremleQuestion[]
  token: string
  created_at?: number
  verify_url?: string
  sources?: KremleSource[]
  attribution?: string
}

export interface UseKremleOptions {
  /** URL для получения challenge (вопросов). Default: '/kremle/challenge' */
  challengeUrl?: string
  /** URL для отправки ответов. Default: '/kremle/verify' */
  verifyUrl?: string
  /** URL для сброса «капча пройдена». Default: выводится из verifyUrl */
  logoutUrl?: string
  /** Автоматически запрашивать новый challenge, если токен истёк. Default: true */
  autoReloadOnExpired?: boolean
  /** Своя функция фингерпринта (например, с дополнительными сигналами) */
  fingerprint?: (honeypot: HoneypotValues) => KremleFingerprint
}

export interface UseKremleReturn {
  questions: KremleQuestion[]
  sources: KremleSource[]
  attribution: string
  token: string
  answers: Record<string, number>
  /** Установить ответ на вопрос questionIndex: индекс варианта optionIndex */
  setAnswer: (questionIndex: number, optionIndex: number) => void
  /** Отправить ответы на сервер */
  submit: (honeypot?: HoneypotValues) => Promise<KremleResult | null>
  /** Загрузить новый challenge */
  reload: () => Promise<void>
  /** Сбросить серверную сессию и получить новый challenge */
  retry: () => Promise<void>
  loading: boolean
  submitting: boolean
  result: KremleResult | null
  error: string | null
  /** Все вопросы отвечены */
  allAnswered: boolean
}

export interface KremleChallengeProps extends UseKremleOptions {
  /** Вызывается при успешном прохождении */
  onPass?: (result: KremleResult) => void
  /** Вызывается при провале */
  onFail?: (result: KremleResult) => void
  /** Вызывается при сетевой ошибке */
  onError?: (message: string) => void
  /** CSS-класс для корневого элемента */
  className?: string
  /** Inline-стили для корневого элемента */
  style?: CSSProperties
  /** Текст заголовка. Default: '[ проверка ]' */
  title?: string
  /** Показывать подпись источника вопросов. Default: true */
  showAttribution?: boolean
  /** Скрыть honeypot-поля (не рекомендуется). Default: false */
  disableHoneypot?: boolean
  /** Дополнительный текст под заголовком */
  description?: string
}

export type { HoneypotValues, KremleFingerprint }
