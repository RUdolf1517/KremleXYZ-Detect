import React, { CSSProperties, useCallback, useEffect, useRef, useState } from 'react'
import { KremleChallenge } from './KremleChallenge'
import type { KremleChallengeProps, KremleResult } from './types'

const overlayStyle: Record<string, CSSProperties> = {
  backdrop: {
    position: 'fixed',
    inset: 0,
    zIndex: 2147483000,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '1.5rem',
    background: 'rgba(0, 0, 0, 0.72)',
    backdropFilter: 'blur(3px)',
    WebkitBackdropFilter: 'blur(3px)',
    overflowY: 'auto',
  },
  card: {
    width: '100%',
    maxWidth: 640,
    maxHeight: 'calc(100vh - 3rem)',
    overflowY: 'auto',
    boxShadow: '0 24px 80px rgba(0, 0, 0, 0.6)',
  },
}

export interface KremleOverlayProps extends KremleChallengeProps {
  /** URL статуса: по нему компонент понимает, что капча ещё не пройдена */
  statusUrl?: string
  /** Проверять статус при монтировании. Default: true */
  checkOnMount?: boolean
  /** Показывать окно принудительно, не спрашивая статус (управляемый режим) */
  open?: boolean
  /** Перезагрузить страницу после прохождения. Default: true */
  reloadOnPass?: boolean
  /** Свой fetch (тесты, SSR, нестандартный транспорт) */
  fetchImpl?: typeof fetch
  /** Вызывается после успешного прохождения, до перезагрузки */
  onSolved?: (result: KremleResult) => void
}

/**
 * Капча поверх страницы вместо отдельной страницы.
 *
 * Спрашивает `/kremle/status`; если сервер помнит «долг капчи» — рисует
 * модальное окно над текущей страницей. Данные при этом остаются за капчей:
 * в режиме `overlay=True` сервер отдаёт переход по ссылке и не отдаёт fetch/API.
 *
 * Пример:
 *   <KremleOverlay onSolved={() => refetchData()} />
 */
export function KremleOverlay({
  statusUrl = '/kremle/status',
  checkOnMount = true,
  open: forcedOpen,
  reloadOnPass = true,
  fetchImpl,
  onSolved,
  onPass,
  onError,
  className,
  ...challengeProps
}: KremleOverlayProps) {
  const [visible, setVisible] = useState(Boolean(forcedOpen))
  const [reason, setReason] = useState<string | null>(null)
  const dialog = useRef<HTMLDivElement>(null)
  const previousOverflow = useRef('')

  const doFetch = useCallback(
    (input: RequestInfo | URL, init?: RequestInit) => {
      const transport = fetchImpl || globalThis.fetch
      if (!transport) return Promise.reject(new Error('fetch недоступен'))
      return transport(input, init)
    },
    [fetchImpl],
  )

  useEffect(() => {
    if (forcedOpen !== undefined) setVisible(forcedOpen)
  }, [forcedOpen])

  useEffect(() => {
    if (!checkOnMount || forcedOpen !== undefined) return
    let cancelled = false
    doFetch(statusUrl, { credentials: 'include', headers: { Accept: 'application/json' } })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return response.json()
      })
      .then((data: { pending?: boolean; verified?: boolean; reason?: string | null }) => {
        if (cancelled) return
        // Статус недоступен или капча не нужна — молчим, страница важнее
        if (data && data.pending && !data.verified) {
          setReason(data.reason || null)
          setVisible(true)
        }
      })
      .catch((error: Error) => {
        if (!cancelled && onError) onError(error.message)
      })
    return () => {
      cancelled = true
    }
  }, [checkOnMount, doFetch, forcedOpen, onError, statusUrl])

  useEffect(() => {
    if (!visible) return
    previousOverflow.current = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    // Фокус на само окно: вопросы приходят асинхронно, и цепляться за первый
    // попавшийся элемент значит потерять фокус при перерисовке
    if (dialog.current) dialog.current.focus()
    return () => {
      document.body.style.overflow = previousOverflow.current
    }
  }, [visible])

  if (!visible) return null

  const handlePass = (result: KremleResult) => {
    setVisible(false)
    if (onPass) onPass(result)
    if (onSolved) onSolved(result)
    if (reloadOnPass && typeof window !== 'undefined' && window.location) {
      window.location.reload()
    }
  }

  return (
    <div
      className="kremle-overlay"
      data-reason={reason || undefined}
      style={overlayStyle.backdrop}
      // Клик по фону окно не закрывает: «закрыть и зайти» — это и есть обход
      onClick={(event) => event.target === event.currentTarget && event.stopPropagation()}
    >
      <div
        ref={dialog}
        className="kremle-overlay-card"
        role="dialog"
        aria-modal="true"
        aria-label={challengeProps.title || '[ проверка ]'}
        tabIndex={-1}
        style={overlayStyle.card}
      >
        <KremleChallenge
          {...challengeProps}
          className={className}
          onPass={handlePass}
          onError={onError}
        />
      </div>
    </div>
  )
}
