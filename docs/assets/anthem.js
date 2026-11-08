/**
 * Гимн России — кнопка «послушать» для сайта документации.
 *
 * Один файл, без зависимостей и без внешних аудио: мелодия синтезируется
 * Web Audio API по нотам. Так сайт не тянет чужой mp3, не зависит от хостинга
 * и не нарушает ничего лишнего — музыка Александрова перешла в общественное
 * достояние, а записей мы не распространяем.
 *
 * Ноты — мелодия из партитуры (труба/струнные), 77 нот, 126 долей в темпе 76.
 * Кнопка появляется сама в правом нижнем углу каждой страницы.
 */
(function () {
  'use strict'

  // [доля от начала, длительность в долях, нота MIDI]
  var NOTES = [
  [0, 2, 63], [2, 2, 68], [4, 3, 65], [7, 0.75, 67],
  [8, 1, 68], [9, 1, 70], [10, 1, 72], [11, 0.75, 73],
  [12, 1.75, 75], [14, 1.75, 75], [16, 2, 73], [18, 1.75, 70],
  [20, 2.75, 68], [23, 1, 72], [24, 1, 70], [25, 1, 68],
  [26, 0.75, 67], [27, 1, 65], [28, 1.75, 63], [30, 0.75, 63],
  [31, 0.75, 63], [32, 2, 63], [34, 2, 68], [36, 2.75, 65],
  [39, 1, 67], [40, 1, 68], [41, 1, 70], [42, 1, 72],
  [43, 0.75, 73], [44, 1.75, 75], [46, 1.75, 75], [48, 1.75, 77],
  [50, 2, 68], [52, 2.75, 72], [55, 0.75, 73], [56, 1.75, 72],
  [58, 1.5, 70], [59.5, 0.5, 72], [60, 2.25, 68], [64, 1.75, 70],
  [66, 2, 70], [68, 2, 70], [70, 1, 68], [71, 1, 70],
  [72, 2, 72], [74, 1.5, 73], [75.5, 0.5, 72], [76, 2, 75],
  [78, 1.5, 72], [80, 1.75, 70], [82, 1.75, 70], [84, 2, 70],
  [86, 1, 72], [87, 1, 70], [88, 2, 68], [90, 1, 67],
  [91, 1, 68], [92, 2.25, 65], [95, 0.75, 63], [96, 2, 63],
  [98, 2, 68], [100, 3, 65], [103, 0.75, 67], [104, 1, 68],
  [105, 1, 70], [106, 1, 72], [107, 0.75, 73], [108, 1.75, 75],
  [110, 1.75, 75], [112, 2, 77], [114, 2, 68], [116, 2.75, 72],
  [119, 1, 73], [120, 2, 72], [122, 1.5, 70], [123.5, 0.5, 72],
  [124, 2.25, 68]
  ]

  var BPM = 76
  var BEAT = 60 / BPM
  var TITLE = 'Гимн России — музыка А. В. Александрова, слова С. В. Михалкова'

  var ICON_PLAY =
    '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" focusable="false">' +
    '<path fill="currentColor" d="M9 18.5a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0zm0-3.2V5.6l11-2.1v13.9a2.5 2.5 0 1 1-2-2.45V7.1l-7 1.35v6.85z"/>' +
    '</svg>'
  var ICON_STOP =
    '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" focusable="false">' +
    '<rect x="6" y="6" width="12" height="12" rx="1.5" fill="currentColor"/></svg>'

  var ctx = null
  var master = null
  var stopTimer = null
  var playing = false

  function styled() {
    var style = document.createElement('style')
    style.textContent = [
      '.kremle-anthem{position:fixed;left:20px;bottom:20px;z-index:900;display:flex;',
      'align-items:center;gap:.55rem;padding:6px 14px 6px 6px;border:0;border-radius:999px;',
      'background:#101010;color:#f5f5f5;cursor:pointer;font:500 13px/1 ui-monospace,SFMono-Regular,',
      'Menlo,Consolas,monospace;letter-spacing:.03em;box-shadow:0 8px 28px rgba(0,0,0,.35);',
      'transition:transform .15s ease,box-shadow .15s ease}',
      '.kremle-anthem:hover{transform:translateY(-1px);box-shadow:0 12px 34px rgba(0,0,0,.45)}',
      '.kremle-anthem:focus-visible{outline:2px solid #d52b1e;outline-offset:3px}',
      '.kremle-anthem__badge{position:relative;display:grid;place-items:center;width:34px;height:34px;',
      'border-radius:50%;background:#f5f5f5;color:#101010;flex:none}',
      '.kremle-anthem__badge::before{content:"";position:absolute;inset:-3px;border-radius:50%;',
      'background:conic-gradient(#ffffff 0 33%,#0039a6 33% 66%,#d52b1e 66% 100%);z-index:-1}',
      '.kremle-anthem[aria-pressed="true"] .kremle-anthem__badge::before{animation:kremle-spin 2.4s linear infinite}',
      '@keyframes kremle-spin{to{transform:rotate(360deg)}}',
      '@media (prefers-reduced-motion:reduce){.kremle-anthem,.kremle-anthem__badge::before{',
      'transition:none;animation:none!important}}',
      '@media (max-width:520px){.kremle-anthem{left:12px;bottom:12px;padding:5px}',
      '.kremle-anthem__label{display:none}}',
    ].join('')
    document.head.appendChild(style)
  }

  function note(freq, at, duration) {
    var gain = ctx.createGain()
    var filter = ctx.createBiquadFilter()
    filter.type = 'lowpass'
    filter.frequency.setValueAtTime(Math.min(5200, freq * 6), at)
    filter.Q.value = 0.6

    var peak = 0.16
    gain.gain.setValueAtTime(0.0001, at)
    gain.gain.exponentialRampToValueAtTime(peak, at + 0.05)
    gain.gain.exponentialRampToValueAtTime(peak * 0.72, at + 0.22)
    gain.gain.setValueAtTime(peak * 0.72, at + Math.max(0.26, duration - 0.12))
    gain.gain.exponentialRampToValueAtTime(0.0001, at + duration)

    // Медные: пила + треугольник, чуть расстроенные — так звук не «синтетический».
    var voices = [
      { type: 'sawtooth', detune: -4, level: 0.55 },
      { type: 'triangle', detune: 4, level: 0.45 },
    ]
    voices.forEach(function (voice) {
      var osc = ctx.createOscillator()
      osc.type = voice.type
      osc.frequency.value = freq
      osc.detune.value = voice.detune
      var level = ctx.createGain()
      level.gain.value = voice.level
      osc.connect(level)
      level.connect(filter)
      osc.start(at)
      osc.stop(at + duration + 0.05)
    })

    // Подголосок октавой ниже — чтобы соло не звучало тонко.
    var bass = ctx.createOscillator()
    bass.type = 'sine'
    bass.frequency.value = freq / 2
    var bassGain = ctx.createGain()
    bassGain.gain.value = 0.28
    bass.connect(bassGain)
    bassGain.connect(filter)
    bass.start(at)
    bass.stop(at + duration + 0.05)

    filter.connect(gain)
    gain.connect(master)
  }

  function build() {
    var AudioCtx = window.AudioContext || window.webkitAudioContext
    if (!AudioCtx) return false
    ctx = new AudioCtx()
    master = ctx.createGain()
    master.gain.value = 0.9
    var compressor = ctx.createDynamicsCompressor()
    compressor.threshold.value = -18
    compressor.ratio.value = 3
    master.connect(compressor)
    compressor.connect(ctx.destination)
    return true
  }

  function play(button) {
    if (!ctx && !build()) {
      button.title = 'Браузер не умеет Web Audio — гимн сыграть нечем'
      return
    }
    if (ctx.state === 'suspended') ctx.resume()
    var start = ctx.currentTime + 0.15
    NOTES.forEach(function (item) {
      var beatStart = item[0]
      var beats = item[1]
      var midi = item[2]
      var freq = 440 * Math.pow(2, (midi - 69) / 12)
      note(freq, start + beatStart * BEAT, Math.max(0.18, beats * BEAT))
    })
    playing = true
    button.setAttribute('aria-pressed', 'true')
    button.querySelector('.kremle-anthem__label').textContent = 'остановить'
    button.querySelector('.kremle-anthem__icon').innerHTML = ICON_STOP
    button.title = 'Остановить гимн'

    var total = (NOTES[NOTES.length - 1][0] + NOTES[NOTES.length - 1][1]) * BEAT + 0.6
    stopTimer = setTimeout(function () { reset(button) }, total * 1000)
  }

  function reset(button) {
    if (stopTimer) { clearTimeout(stopTimer); stopTimer = null }
    playing = false
    if (ctx) { try { ctx.close() } catch (e) {} ctx = null; master = null }
    button.setAttribute('aria-pressed', 'false')
    button.querySelector('.kremle-anthem__label').textContent = 'гимн'
    button.querySelector('.kremle-anthem__icon').innerHTML = ICON_PLAY
    button.title = TITLE + '. Нажмите, чтобы послушать'
  }

  function mount() {
    if (document.querySelector('.kremle-anthem')) return
    styled()
    var button = document.createElement('button')
    button.type = 'button'
    button.className = 'kremle-anthem'
    button.setAttribute('aria-pressed', 'false')
    button.setAttribute('aria-label', 'Прослушать гимн России')
    button.title = TITLE + '. Нажмите, чтобы послушать'
    button.innerHTML =
      '<span class="kremle-anthem__badge"><span class="kremle-anthem__icon">' + ICON_PLAY +
      '</span></span><span class="kremle-anthem__label">гимн</span>'

    button.addEventListener('click', function () {
      if (playing) reset(button)
      else play(button)
    })
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && playing) reset(button)
    })
    document.body.appendChild(button)
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount)
  } else {
    mount()
  }
})()
