import type { CSSProperties } from 'react'

export interface KremleQuestion {
  q: string
  opts: string[]
  category?: string
}

export interface KremleResult {
  passed: boolean
  errors: number
  total: number
  redirect?: string | null
  error?: string
}

export interface UseKremleOptions {
  /** URL для получения challenge (вопросов). Default: '/kremle/challenge' */
  challengeUrl?: string
  /** URL для отправки ответов. Default: '/kremle/verify' */
  verifyUrl?: string
}

export interface UseKremleReturn {
  questions: KremleQuestion[]
  token: string
  answers: Record<string, number>
  /** Установить ответ на вопрос questionIndex: индекс варианта optionIndex */
  setAnswer: (questionIndex: number, optionIndex: number) => void
  /** Отправить ответы на сервер */
  submit: () => Promise<KremleResult | null>
  /** Загрузить новый challenge */
  reload: () => Promise<void>
  loading: boolean
  submitting: boolean
  result: KremleResult | null
  error: string | null
}

export interface KremleChallengeProps extends UseKremleOptions {
  /** Вызывается при успешном прохождении */
  onPass?: (result: KremleResult) => void
  /** Вызывается при провале */
  onFail?: (result: KremleResult) => void
  /** CSS-класс для корневого элемента */
  className?: string
  /** Inline-стили для корневого элемента */
  style?: CSSProperties
  /** Текст заголовка. Default: '[ проверка ]' */
  title?: string
}
