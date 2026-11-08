/**
 * Капча поверх страницы: модальное окно вместо отдельной страницы.
 *
 * Отдельная страница — честно и просто, но человек теряет то место, куда шёл.
 * Окно поверх сохраняет контекст: страница под ним уже загружена, а данные
 * остаются за капчей (сервер отдаёт переход по ссылке и не отдаёт fetch/API,
 * см. `overlay=True` в интеграциях).
 *
 * Пример — сервер в режиме `overlay=True`, на странице:
 *   <script src="/kremle/widget/kremle-widget.min.js"></script>
 *   <script>KremleWidget.guardOverlay()</script>
 *
 * Виджет сам спросит `/kremle/status`: если капча ещё не пройдена —
 * покажет окно, после прохождения перезагрузит страницу.
 */

import { createWidget } from './widget.js'

const OVERLAY_STYLE = {
  backdrop: {
    position: 'fixed',
    inset: '0',
    zIndex: '2147483000',
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
    maxWidth: '640px',
    width: '100%',
    maxHeight: 'calc(100vh - 3rem)',
    overflowY: 'auto',
    boxShadow: '0 24px 80px rgba(0, 0, 0, 0.6)',
  },
}

const DEFAULTS = {
  statusUrl: '/kremle/status',
  challengeUrl: '/kremle/challenge',
  verifyUrl: '/kremle/verify',
  title: '[ проверка ]',
  description: 'Сайт проверяет, что за браузером человек. Это ненадолго.',
  reloadOnPass: true,
  autoCheck: true,
  fetch: null,
  onSolved: null,
  onError: null,
  widgetOptions: {},
}

function element(tag, style) {
  const node = document.createElement(tag)
  if (style) Object.assign(node.style, style)
  return node
}

function focusable(card) {
  return Array.from(
    card.querySelectorAll('button, input, a[href], [tabindex]:not([tabindex="-1"])'),
  ).filter((node) => !node.disabled && node.tabIndex !== -1)
}

/**
 * Создать сторож: спросить статус и, если капча не пройдена, открыть окно.
 *
 * Returns:
 *   { element, check, open, close, destroy, widget, getState }
 */
export function guardOverlay(options = {}) {
  const config = { ...DEFAULTS, ...options }
  const fetchImpl = config.fetch || ((...args) => window.fetch(...args))
  const state = {
    open: false,
    checking: false,
    solved: false,
    pending: false,
    reason: null,
    error: null,
    destroyed: false,
  }

  let backdrop = null
  let card = null
  let widget = null
  let previousOverflow = ''

  function build() {
    backdrop = element('div', OVERLAY_STYLE.backdrop)
    backdrop.className = 'kremle-overlay'

    card = element('div', OVERLAY_STYLE.card)
    card.className = 'kremle-overlay-card'
    card.setAttribute('role', 'dialog')
    card.setAttribute('aria-modal', 'true')
    card.setAttribute('aria-label', config.title)

    backdrop.appendChild(card)
    // Клик по фону окно не закрывает: «закрыть и зайти» — это и есть обход.
    backdrop.addEventListener('click', (event) => {
      if (event.target === backdrop) event.stopPropagation()
    })
    card.addEventListener('keydown', (event) => trapFocus(event))
    ;(document.body || document.documentElement).appendChild(backdrop)

    previousOverflow = document.body ? document.body.style.overflow : ''
    if (document.body) document.body.style.overflow = 'hidden'
  }

  function trapFocus(event) {
    if (event.key !== 'Tab') return
    const items = focusable(card)
    if (!items.length) return
    const first = items[0]
    const last = items[items.length - 1]
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  function open() {
    if (state.destroyed || state.open) return
    state.open = true
    build()

    widget = createWidget(card, {
      challengeUrl: config.challengeUrl,
      verifyUrl: config.verifyUrl,
      title: config.title,
      description: config.description,
      ...config.widgetOptions,
      // тот же транспорт, что и у статуса: иначе в средах без window.fetch
      // окно откроется с ошибкой сети вместо вопросов
      fetch: config.widgetOptions.fetch || config.fetch || null,
      // свой обработчик поверх пользовательского: окно обязано закрыться
      onPass: (result) => {
        if (config.widgetOptions.onPass) config.widgetOptions.onPass(result)
        solved(result)
      },
    })

    // Фокус — на само окно: вопросы приходят асинхронно, и хватать первый
    // попавшийся элемент раньше времени значит потерять его при перерисовке.
    // Дальше Tab ходит по вложенным полям (ловушка ниже).
    card.tabIndex = -1
    card.focus()
  }

  function solved(result) {
    state.solved = true
    state.pending = false
    if (config.onSolved) config.onSolved(result)
    close()
    if (config.reloadOnPass && typeof window !== 'undefined' && window.location) {
      window.location.reload()
    }
  }

  function close() {
    if (widget) {
      widget.destroy()
      widget = null
    }
    if (backdrop && backdrop.parentNode) backdrop.parentNode.removeChild(backdrop)
    backdrop = null
    card = null
    state.open = false
    if (document.body) document.body.style.overflow = previousOverflow
  }

  async function check() {
    if (state.destroyed) return null
    state.checking = true
    state.error = null
    try {
      const response = await fetchImpl(config.statusUrl, {
        credentials: 'include',
        headers: { Accept: 'application/json' },
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const data = await response.json()
      if (state.destroyed) return data
      state.pending = Boolean(data && data.pending) && !data.verified
      state.reason = (data && data.reason) || null
      if (state.pending) open()
      return data
    } catch (e) {
      // Статус недоступен — молчим: сервер всё равно не пустит данные,
      // а пугать человека сетевой ошибкой на каждой странице незачем.
      state.error = e && e.message ? e.message : 'status unavailable'
      if (config.onError) config.onError(state.error)
      return null
    } finally {
      state.checking = false
    }
  }

  function destroy() {
    state.destroyed = true
    close()
  }

  function getState() {
    return { ...state }
  }

  if (config.autoCheck) void check()

  return { check, open, close, destroy, getState, get element() { return backdrop } }
}

/**
 * Проверить статус после загрузки страницы.
 *
 * Вызывается из `<script>` после бандла: `KremleWidget.autoGuardOverlay()`.
 * Можно передать `{autoCheck: false}` и дёргать `check()` руками (например,
 * после входа в SPA-роут).
 */
export function autoGuardOverlay(
  rootDocument = typeof document === 'undefined' ? null : document,
  options = {},
) {
  if (!rootDocument) return null
  const start = () => guardOverlay(options)
  if (rootDocument.readyState === 'loading') {
    rootDocument.addEventListener('DOMContentLoaded', start, { once: true })
    return null
  }
  return start()
}
