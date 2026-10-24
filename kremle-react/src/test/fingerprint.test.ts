import { describe, expect, it, vi, afterEach } from 'vitest'
import { collectFingerprint } from '../fingerprint'

function setUserAgent(ua: string) {
  vi.spyOn(window.navigator, 'userAgent', 'get').mockReturnValue(ua)
}

describe('collectFingerprint', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    delete (window as any).yandex
    delete (window as any).Ya
  })

  it('обычный браузер: сигналов нет', () => {
    setUserAgent('Mozilla/5.0 Chrome/120.0 Safari/537.36')
    const fp = collectFingerprint()
    expect(fp.yaBrands).toBe(false)
    expect(fp.yandexApi).toBe(false)
    expect(fp.honeypot).toBe(false)
  })

  it('ловит YaBrowser в User-Agent', () => {
    setUserAgent('Mozilla/5.0 YaBrowser/24.1 Safari/537.36')
    expect(collectFingerprint().yaBrands).toBe(true)
  })

  it('ловит userAgentData.brands', () => {
    setUserAgent('Mozilla/5.0 Chrome/120')
    Object.defineProperty(navigator, 'userAgentData', {
      configurable: true,
      value: { brands: [{ brand: 'Chromium' }, { brand: 'YaBrowser' }] },
    })
    const fp = collectFingerprint()
    expect(fp.yaBrands).toBe(true)
    expect(fp.brands).toEqual(['Chromium', 'YaBrowser'])
    // @ts-expect-error cleanup
    delete navigator.userAgentData
  })

  it('ловит window.yandex', () => {
    setUserAgent('Mozilla/5.0 Chrome/120')
    ;(window as any).yandex = {}
    expect(collectFingerprint().yandexApi).toBe(true)
  })

  it('заполненный honeypot', () => {
    setUserAgent('Mozilla/5.0 Chrome/120')
    expect(collectFingerprint({ name: 'bot' }).honeypot).toBe(true)
    expect(collectFingerprint({ email: 'a@b.c' }).honeypot).toBe(true)
    expect(collectFingerprint({ name: '   ' }).honeypot).toBe(false)
  })

  it('возвращает webdriver и язык', () => {
    setUserAgent('Mozilla/5.0 Chrome/120')
    Object.defineProperty(navigator, 'webdriver', { configurable: true, value: true })
    const fp = collectFingerprint()
    expect(fp.webdriver).toBe(true)
    expect(typeof fp.lang).toBe('string')
    // @ts-expect-error cleanup
    delete navigator.webdriver
  })
})
