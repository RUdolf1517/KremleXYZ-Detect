import React, { CSSProperties, useEffect, useRef } from 'react'
import { useKremle } from './useKremle'
import type { KremleChallengeProps, KremleResult } from './types'

const base: Record<string, CSSProperties> = {
  container: {
    fontFamily: 'monospace',
    background: '#0a0a0a',
    color: '#ffffff',
    padding: '2rem',
    maxWidth: '600px',
    border: '1px solid #2a2a2a',
    boxSizing: 'border-box',
  },
  title: {
    fontSize: '1.25rem',
    marginBottom: '0.5rem',
    letterSpacing: '0.05em',
  },
  description: {
    color: '#888888',
    fontSize: '0.85rem',
    marginBottom: '1.25rem',
    lineHeight: 1.5,
  },
  question: {
    marginBottom: '1.25rem',
    paddingBottom: '1.25rem',
    borderBottom: '1px solid #1e1e1e',
  },
  images: { margin: '0.5rem 0' },
  image: {
    maxWidth: '100%',
    maxHeight: 220,
    display: 'block',
    margin: '0.35rem 0',
    border: '1px solid #2a2a2a',
    background: '#fff',
  },
  questionText: {
    marginBottom: '0.6rem',
    lineHeight: 1.5,
    color: '#cccccc',
  },
  label: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    padding: '0.3rem 0',
    cursor: 'pointer',
    color: '#666666',
    transition: 'color 0.15s',
  },
  labelSelected: {
    color: '#ffffff',
  },
  radio: {
    accentColor: '#ffffff',
    cursor: 'pointer',
  },
  btn: {
    marginTop: '1rem',
    background: 'transparent',
    border: '1px solid #ffffff',
    color: '#ffffff',
    fontFamily: 'monospace',
    fontSize: '1rem',
    padding: '0.5rem 1.25rem',
    cursor: 'pointer',
    letterSpacing: '0.04em',
  },
  btnDisabled: {
    opacity: 0.35,
    cursor: 'not-allowed',
  },
  resultBox: {
    marginTop: '1rem',
    padding: '0.75rem 1rem',
    border: '1px solid',
    fontFamily: 'monospace',
  },
  resultPass: {
    borderColor: '#4caf50',
    color: '#4caf50',
  },
  resultFail: {
    borderColor: '#f44336',
    color: '#f44336',
  },
  error: {
    color: '#f44336',
    marginBottom: '0.75rem',
  },
  honeypot: {
    position: 'absolute',
    left: '-9999px',
    top: '-9999px',
    width: '1px',
    height: '1px',
    opacity: 0,
    pointerEvents: 'none',
  },
  attribution: {
    marginTop: '1.25rem',
    paddingTop: '0.75rem',
    borderTop: '1px solid #1e1e1e',
    color: '#666666',
    fontSize: '0.75rem',
  },
  attributionLink: {
    color: '#888888',
  },
}

function resultMessage(result: KremleResult): string {
  if (result.passed) return `пройдено — ошибок: ${result.errors}/${result.total}`
  if (result.error === 'rate_limited') return 'слишком много попыток — попробуйте позже'
  if (result.error === 'blacklisted' || result.error === 'blocked') return 'доступ заблокирован'
  if (result.error === 'invalid_token') return 'проверка устарела — начните заново'
  if (result.error) return `ошибка: ${result.error}`
  return `провал — ошибок: ${result.errors}/${result.total}`
}

/**
 * Готовая капча для React-фронтенда.
 *
 * Пример:
 *   <KremleChallenge onPass={() => window.location.reload()} />
 */
export function KremleChallenge({
  challengeUrl = '/kremle/challenge',
  verifyUrl = '/kremle/verify',
  logoutUrl,
  autoReloadOnExpired,
  fingerprint,
  onPass,
  onFail,
  onError,
  className,
  style,
  title = '[ проверка ]',
  description,
  showAttribution = true,
  disableHoneypot = false,
}: KremleChallengeProps) {
  const {
    questions,
    sources,
    attribution,
    answers,
    setAnswer,
    submit,
    retry,
    loading,
    submitting,
    result,
    error,
    allAnswered,
  } = useKremle({
    challengeUrl,
    verifyUrl,
    logoutUrl,
    autoReloadOnExpired,
    fingerprint,
  })

  const honeypotName = useRef<HTMLInputElement>(null)
  const honeypotEmail = useRef<HTMLInputElement>(null)
  const notified = useRef<KremleResult | null>(null)

  useEffect(() => {
    if (!result || notified.current === result) return
    notified.current = result
    if (result.passed) {
      onPass?.(result)
      if (result.redirect && typeof window !== 'undefined') {
        window.location.href = result.redirect
      }
    } else {
      onFail?.(result)
    }
  }, [result, onPass, onFail])

  useEffect(() => {
    if (error) onError?.(error)
  }, [error, onError])

  const containerStyle: CSSProperties = { ...base.container, ...style }

  if (loading) {
    return (
      <div style={containerStyle} className={className} aria-busy="true">
        <span style={{ color: '#666666' }}>[ загрузка... ]</span>
      </div>
    )
  }

  return (
    <div style={containerStyle} className={className}>
      <div style={base.title}>{title}</div>
      {description && <div style={base.description}>{description}</div>}

      {error && (
        <div style={base.error} role="alert">
          ошибка: {error}
        </div>
      )}

      {!disableHoneypot && (
        <div style={base.honeypot} aria-hidden="true">
          <input ref={honeypotName} type="text" name="kremle_name" tabIndex={-1} autoComplete="off" />
          <input ref={honeypotEmail} type="email" name="kremle_email" tabIndex={-1} autoComplete="off" />
        </div>
      )}

      {questions.map((q, qi) => (
        <fieldset
          key={qi}
          style={{ ...base.question, border: 'none', borderBottom: '1px solid #1e1e1e', padding: 0, margin: 0 }}
        >
          <legend style={{ ...base.questionText, padding: 0 }}>{`${qi + 1}. ${q.q}`}</legend>
          {q.images && q.images.length > 0 && (
            <div style={base.images}>
              {q.images.map((img, ii) => (
                <img
                  key={ii}
                  src={img.url}
                  alt={img.alt || 'рисунок к заданию'}
                  loading="lazy"
                  referrerPolicy="no-referrer"
                  style={base.image}
                  onError={(e) => {
                    // Порталу может не понравиться горячая ссылка: капчу не ломаем
                    const el = e.currentTarget
                    el.style.display = 'none'
                    if (!el.dataset.failed) {
                      el.dataset.failed = '1'
                      el.insertAdjacentText('afterend', ' [рисунок не загрузился]')
                    }
                  }}
                />
              ))}
            </div>
          )}
          {q.opts.map((opt, oi) => {
            const selected = answers[String(qi)] === oi
            return (
              <label key={oi} style={{ ...base.label, ...(selected ? base.labelSelected : {}) }}>
                <input
                  type="radio"
                  name={`kremle_q${qi}`}
                  value={oi}
                  checked={selected}
                  onChange={() => setAnswer(qi, oi)}
                  style={base.radio}
                />
                {opt}
              </label>
            )
          })}
        </fieldset>
      ))}

      {result ? (
        <ResultBox
          result={result}
          onRetry={retry}
        />
      ) : (
        <button
          type="button"
          style={{ ...base.btn, ...(!allAnswered || submitting ? base.btnDisabled : {}) }}
          onClick={() =>
            submit({
              name: honeypotName.current?.value ?? '',
              email: honeypotEmail.current?.value ?? '',
            })
          }
          disabled={!allAnswered || submitting}
        >
          {submitting ? '[ проверка... ]' : '[ отправить ]'}
        </button>
      )}

      {showAttribution && (sources.length > 0 || attribution) && (
        <div style={base.attribution}>
          {/* sources — структурированные ссылки; attribution — готовая строка
              от сервера, если структуры нет */}
          {sources.length > 0 ? 'Задания: ' : attribution}
          {sources.map((src, i) => (
            <React.Fragment key={`${src.name}-${i}`}>
              {i > 0 && ', '}
              {src.url ? (
                <a
                  href={src.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={base.attributionLink}
                  title={src.author}
                >
                  {src.name}
                </a>
              ) : (
                src.name
              )}
            </React.Fragment>
          ))}
        </div>
      )}
    </div>
  )
}

function ResultBox({
  result,
  onRetry,
}: {
  result: KremleResult
  onRetry: () => void
}) {
  const message = resultMessage(result)

  if (result.passed) {
    return (
      <div style={{ ...base.resultBox, ...base.resultPass }} role="status">
        {message}
      </div>
    )
  }

  return (
    <div style={{ ...base.resultBox, ...base.resultFail }} role="alert">
      {message}
      <button
        type="button"
        style={{ ...base.btn, marginLeft: '1rem', marginTop: 0, fontSize: '0.875rem' }}
        onClick={onRetry}
      >
        [ попробовать снова ]
      </button>
    </div>
  )
}
