/**
 * Фейковый сервер kremle-detect для тестов виджета.
 *
 * Повторяет протокол Flask/FastAPI-интеграций: JSON-челлендж на GET, проверка
 * на POST, те же поля ответа. Если виджет разъедется с сервером — разъедутся
 * и эти тесты, и сценарий из `tests/test_widget_protocol.py`.
 */

const QUESTIONS = [
  { q: 'Производная x² равна:', opts: ['2x', 'x²/2', 'x', '2'], category: 'math' },
  { q: 'log₂(8) равен:', opts: ['3', '4', '2', '8'], category: 'math' },
]

export function createServer(options = {}) {
  const config = {
    maxErrors: 1,
    expiresIn: 900,
    verifyAnswers: options.verifyAnswers || { 0: 0, 1: 0 },
    failOn: options.failOn || null,
    ...options,
  }

  const calls = { challenge: 0, verify: [], logout: 0 }
  let issued = 0

  async function fetchImpl(url, init = {}) {
    const target = String(url)
    const method = (init.method || 'GET').toUpperCase()

    if (target.endsWith('/challenge') && method === 'GET') {
      calls.challenge += 1
      if (config.failOn === 'challenge') {
        return response({ error: 'boom' }, 500)
      }
      issued += 1
      return response({
        questions: config.questions || QUESTIONS,
        token: `token-${issued}`,
        created_at: 1700000000,
        verify_url: '/kremle/verify',
        expires_in: config.expiresIn,
        max_errors: config.maxErrors,
        sources: [],
        attribution: '',
      })
    }

    if (target.endsWith('/verify') && method === 'POST') {
      const body = JSON.parse(init.body || '{}')
      calls.verify.push(body)
      if (config.failOn === 'verify') return response({ error: 'boom' }, 500)

      const answers = body.answers || {}
      const errors = Object.entries(config.verifyAnswers).filter(
        ([index, expected]) => answers[String(index)] !== expected,
      ).length
      const passed = errors <= config.maxErrors
      return response({
        passed,
        errors,
        total: Object.keys(config.verifyAnswers).length,
        max_errors: config.maxErrors,
        redirect: passed ? (config.redirect || '/secret') : null,
      })
    }

    if (target.endsWith('/logout') && method === 'POST') {
      calls.logout += 1
      return response({ verified: false })
    }

    return response({ error: 'not_found' }, 404)
  }

  return { fetchImpl, calls, config }
}

function response(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  }
}
