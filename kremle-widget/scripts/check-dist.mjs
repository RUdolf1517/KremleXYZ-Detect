/**
 * Проверка собранного IIFE: файл из `dist/` действительно ставит капчу
 * одним `<script src>`, без импортов и сборки на стороне пользователя.
 *
 * Запускается после `npm run build` (в CI — отдельным шагом).
 */
import { readFileSync } from 'node:fs'

import { JSDOM } from 'jsdom'

const bundle = readFileSync(new URL('../dist/kremle-widget.min.js', import.meta.url), 'utf8')

const dom = new JSDOM('<!doctype html><div id="kremle"></div>', {
  runScripts: 'outside-only',
  url: 'https://example.test/',
})

const { window } = dom
window.fetch = async (url, init = {}) => {
  if (String(url).endsWith('/challenge')) {
    return {
      ok: true,
      status: 200,
      json: async () => ({
        questions: [{ q: 'Сколько будет 2 + 2?', opts: ['4', '5', '6', '7'] }],
        token: 'token-dist',
        expires_in: 60,
        max_errors: 0,
      }),
    }
  }
  if (String(url).endsWith('/verify')) {
    const body = JSON.parse(init.body)
    const passed = body.answers['0'] === 0 && body.token === 'token-dist'
    return {
      ok: true,
      status: 200,
      json: async () => ({ passed, errors: passed ? 0 : 1, total: 1, max_errors: 0 }),
    }
  }
  return { ok: false, status: 404, json: async () => ({}) }
}

window.eval(bundle)

if (!window.KremleWidget || typeof window.KremleWidget.mount !== 'function') {
  throw new Error('IIFE-бандл не выставил глобальный KremleWidget.mount')
}

const widget = window.KremleWidget.mount('#kremle')
await new Promise((resolve) => setTimeout(resolve, 20))

const radios = window.document.querySelectorAll('input[type=radio]')
if (radios.length !== 4) {
  throw new Error(`ожидалось 4 варианта ответа, отрисовано ${radios.length}`)
}
radios[0].click()
window.document.querySelector('.kremle-submit').click()
await new Promise((resolve) => setTimeout(resolve, 20))

const result = window.document.querySelector('.kremle-result')
if (!result || !result.textContent.includes('пройдено')) {
  throw new Error(`капча не прошла: ${result ? result.textContent : 'нет результата'}`)
}

widget.destroy()
console.log('IIFE ok:', (bundle.length / 1024).toFixed(1), 'КБ, капча пройдена без сборки')
