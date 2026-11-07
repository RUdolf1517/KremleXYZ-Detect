/**
 * Статическое демо (`docs/demo.html`) должно действительно работать:
 * страница открывается без сервера, рисует капчу и проверяет ответы локально.
 *
 * Внешний `<script src>` в jsdom не грузится, поэтому бандл подставляем
 * глобальным объектом — тест проверяет саму страницу, а не загрузчик.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { afterEach, describe, expect, it, vi } from 'vitest'

import * as KremleWidget from '../src/index.js'

const demoPath = resolve(process.cwd(), '..', 'docs', 'demo.html')
const html = readFileSync(demoPath, 'utf8')

const tick = (ms = 250) => new Promise((resolve) => setTimeout(resolve, ms))

let mounted

afterEach(() => {
  if (mounted) mounted.destroy()
  mounted = undefined
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

/** Выполнить разметку и инлайновый скрипт демо-страницы в текущем jsdom. */
function runDemo() {
  const body = html.match(/<body>([\s\S]*?)<script src/)
  const inline = html.match(/<script>([\s\S]*?)<\/script>\s*<\/body>/)
  if (!body || !inline) throw new Error('в demo.html не нашлись разметка или скрипт')

  document.body.innerHTML = body[1]
  globalThis.KremleWidget = {
    ...KremleWidget,
    mount(target, options) {
      mounted = KremleWidget.mount(target, options)
      return mounted
    },
  }
  new Function(inline[1])()
}

describe('docs/demo.html', () => {
  it('грузит бандл относительной ссылкой и монтирует капчу', () => {
    expect(html).toContain('<script src="./assets/kremle-widget.min.js"></script>')
    expect(html).toContain("KremleWidget.mount('#kremle'")
    expect(html).toContain('id="kremle"')
  })

  it('честно предупреждает, что ответы зашиты в страницу', () => {
    // текст в разметке переносится по строкам — сверяем без переносов
    expect(html.replace(/\s+/g, ' ')).toContain('Правильные ответы лежат в коде страницы')
    expect(html).toContain('/kremle/verify')
  })

  it('рисует задания и не отправляет неполный ответ', async () => {
    runDemo()
    await tick()

    expect(document.querySelectorAll('label').length).toBeGreaterThan(0)
    document.querySelectorAll('input[type=radio]')[0].click()
    document.querySelector('.kremle-submit').click()
    await tick()

    expect(document.body.textContent).toContain('ответьте на все вопросы')
  })

  it('проверяет ответы локально и показывает результат', async () => {
    runDemo()
    await tick()

    expect(mounted.getState().questions.length).toBe(3)

    // выбираем правильный вариант в каждом вопросе (демо знает их у себя)
    const correct = window.__demoQuestions.map((question) => question._correct)
    correct.forEach((optionIndex, questionIndex) => {
      const inputs = document.querySelectorAll(`input[name=kremle-q${questionIndex}]`)
      inputs[optionIndex].click()
    })
    document.querySelector('.kremle-submit').click()
    await tick(400)

    const result = document.querySelector('.kremle-result')
    expect(result).toBeTruthy()
    expect(result.textContent).toContain('пройдено')
    expect(result.textContent).toContain('ошибок: 0/3')
  })
})
