import React, { CSSProperties, useEffect } from 'react'
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
    marginBottom: '1.5rem',
    letterSpacing: '0.05em',
  },
  question: {
    marginBottom: '1.25rem',
    paddingBottom: '1.25rem',
    borderBottom: '1px solid #1e1e1e',
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
}

export function KremleChallenge({
  challengeUrl = '/kremle/challenge',
  verifyUrl = '/kremle/verify',
  onPass,
  onFail,
  className,
  style,
  title = '[ проверка ]',
}: KremleChallengeProps) {
  const {
    questions,
    answers,
    setAnswer,
    submit,
    reload,
    loading,
    submitting,
    result,
    error,
  } = useKremle({ challengeUrl, verifyUrl })

  useEffect(() => {
    if (!result) return
    if (result.passed) {
      onPass?.(result)
      if (result.redirect) {
        window.location.href = result.redirect
      }
    } else {
      onFail?.(result)
    }
  }, [result]) // eslint-disable-line react-hooks/exhaustive-deps

  const allAnswered =
    questions.length > 0 &&
    questions.every((_, i) => answers[String(i)] !== undefined)

  const containerStyle: CSSProperties = { ...base.container, ...style }

  if (loading) {
    return (
      <div style={containerStyle} className={className}>
        <span style={{ color: '#666666' }}>[ загрузка... ]</span>
      </div>
    )
  }

  return (
    <div style={containerStyle} className={className}>
      <div style={base.title}>{title}</div>

      {error && <div style={base.error}>ошибка: {error}</div>}

      {questions.map((q, qi) => (
        <div key={qi} style={base.question}>
          <div style={base.questionText}>
            {qi + 1}. {q.q}
          </div>
          {q.opts.map((opt, oi) => {
            const selected = answers[String(qi)] === oi
            return (
              <label
                key={oi}
                style={{ ...base.label, ...(selected ? base.labelSelected : {}) }}
              >
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
        </div>
      ))}

      {result ? (
        <ResultBox result={result} onRetry={reload} />
      ) : (
        <button
          style={{
            ...base.btn,
            ...(!allAnswered || submitting ? base.btnDisabled : {}),
          }}
          onClick={submit}
          disabled={!allAnswered || submitting}
        >
          {submitting ? '[ проверка... ]' : '[ отправить ]'}
        </button>
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
  if (result.passed) {
    return (
      <div style={{ ...base.resultBox, ...base.resultPass }}>
        пройдено — ошибок: {result.errors}/{result.total}
      </div>
    )
  }
  return (
    <div style={{ ...base.resultBox, ...base.resultFail }}>
      провал — ошибок: {result.errors}/{result.total}
      <button
        style={{ ...base.btn, marginLeft: '1rem', marginTop: 0, fontSize: '0.875rem' }}
        onClick={onRetry}
      >
        [ попробовать снова ]
      </button>
    </div>
  )
}
