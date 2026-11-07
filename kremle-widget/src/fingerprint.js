/**
 * Фингерпринт клиента — пять сигналов, ровно столько, сколько читает сервер.
 *
 * Набор обязан совпадать с `kremle_detect/templates/kremle_captcha.html` и с
 * `collectFingerprint` из `kremle-react`: полный User-Agent, список брендов и
 * язык не отправляются, решение по ним не принимается.
 */
export function collectFingerprint(honeypot = {}) {
  const fp = {
    yaBrands: false,
    yandexApi: false,
    honeypot: false,
    webdriver: false,
    timezone: '',
  }

  try {
    const uaData = navigator.userAgentData
    if (uaData && Array.isArray(uaData.brands)) {
      fp.yaBrands = uaData.brands.some((entry) =>
        /YaBrowser|Yandex/i.test((entry && entry.brand) || ''),
      )
    }
    if (!fp.yaBrands) {
      fp.yaBrands = /YaBrowser|Yowser/i.test(navigator.userAgent || '')
    }

    fp.yandexApi = Boolean(window.yandex || window.Ya || window.YaBrowser)
    fp.webdriver = Boolean(navigator.webdriver)
    fp.honeypot = Boolean(
      (honeypot.name && honeypot.name.trim().length > 0) ||
        (honeypot.email && honeypot.email.trim().length > 0),
    )

    try {
      fp.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || ''
    } catch {
      fp.timezone = ''
    }
  } catch (e) {
    // Фингерпринт — необязательный сигнал: его отсутствие не должно ломать капчу.
    fp.error = e && e.message
  }

  return fp
}
