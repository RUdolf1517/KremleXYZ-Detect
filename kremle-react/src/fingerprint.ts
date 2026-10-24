/**
 * Клиентский фингерпринт для капчи.
 *
 * Собирается только в браузере: при SSR (`typeof window === 'undefined'`)
 * возвращаются безопасные значения по умолчанию, чтобы компонент не падал
 * в Next.js/Remix.
 */

export interface KremleFingerprint {
  /** Яндекс Браузер в navigator.userAgentData.brands (Client Hints JS API) */
  yaBrands: boolean
  /** Яндекс-специфичные объекты в window */
  yandexApi: boolean
  /** Заполнены скрытые honeypot-поля (типичный признак бота) */
  honeypot: boolean
  /** Полный список брендов, если браузер его отдаёт */
  brands?: string[]
  /** navigator.webdriver — автоматизация через Selenium/Puppeteer */
  webdriver?: boolean
  /** Язык интерфейса */
  lang?: string
  /** Часовой пояс */
  tz?: string
}

export interface HoneypotValues {
  name?: string
  email?: string
}

function getWindow(): (Window & typeof globalThis) | null {
  return typeof window === 'undefined' ? null : window
}

/**
 * Собирает фингерпринт.
 *
 * Пример:
 *   const fp = collectFingerprint({ name: nameRef.current?.value })
 *   // → { yaBrands: false, yandexApi: false, honeypot: false, ... }
 */
export function collectFingerprint(honeypot: HoneypotValues = {}): KremleFingerprint {
  const win = getWindow()

  const honeypotFilled = Boolean(
    (honeypot.name && honeypot.name.trim().length > 0) ||
    (honeypot.email && honeypot.email.trim().length > 0),
  )

  if (!win || typeof navigator === 'undefined') {
    return { yaBrands: false, yandexApi: false, honeypot: honeypotFilled }
  }

  const ua = navigator.userAgent || ''
  const uaData = (navigator as Navigator & {
    userAgentData?: { brands?: Array<{ brand: string }> }
  }).userAgentData

  const brands = Array.isArray(uaData?.brands)
    ? uaData!.brands!.map((b) => b?.brand ?? '').filter(Boolean)
    : undefined

  const yaBrands = Boolean(
    brands?.some((b) => /YaBrowser|Yandex/i.test(b)) || /YaBrowser|Yowser/i.test(ua),
  )

  const yandexApi = Boolean(
    (win as unknown as Record<string, unknown>).yandex ||
    (win as unknown as Record<string, unknown>).Ya ||
    (win as unknown as Record<string, unknown>).YaBrowser,
  )

  const fp: KremleFingerprint = {
    yaBrands,
    yandexApi,
    honeypot: honeypotFilled,
    webdriver: Boolean((navigator as Navigator & { webdriver?: boolean }).webdriver),
    lang: navigator.language || '',
  }

  if (brands) fp.brands = brands

  try {
    fp.tz = Intl.DateTimeFormat().resolvedOptions().timeZone || ''
  } catch {
    fp.tz = ''
  }

  return fp
}
