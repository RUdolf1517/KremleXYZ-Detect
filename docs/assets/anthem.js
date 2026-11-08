/**
 * Гимн России — кнопка «послушать» для сайта документации.
 *
 * Мелодия синтезируется в браузере по нотам из партитуры: партия корнета 1
 * (инструмент в B♭) из партитуры А. В. Александрова, транспонированная в
 * звучащий до мажор. Никаких внешних mp3 и чужих записей — только ноты.
 * Темп 76, как в регламенте исполнения.
 *
 * Кнопка появляется сама в левом нижнем углу каждой страницы.
 */
(function () {
  'use strict'

  // [доля от начала, длительность в долях, нота MIDI]; доля — четверть
  var NOTES = [
  [0, 3, 72], [3.5, 0.5, 67], [4, 1, 72], [5, 0.75, 67],
  [5.75, 0.25, 69], [6, 1, 71], [7, 0.5, 64], [7.5, 0.5, 64],
  [8, 1, 69], [9, 0.75, 67], [9.75, 0.25, 65], [10, 1, 67],
  [11, 0.5, 60], [11.5, 0.5, 60], [12, 1, 62], [13, 0.75, 62],
  [13.75, 0.25, 64], [14, 1, 65], [15, 0.75, 65], [15.75, 0.25, 67],
  [16, 1, 69], [17, 0.5, 71], [17.5, 0.5, 72], [18, 1.5, 74],
  [19.5, 0.5, 67], [20, 1, 76], [21, 0.75, 74], [21.75, 0.25, 72],
  [22, 1, 74], [23, 0.5, 71], [23.5, 0.5, 67], [24, 1, 72],
  [25, 0.75, 71], [25.75, 0.25, 69], [26, 1, 71], [27, 0.5, 64],
  [27.5, 0.5, 64], [28, 1, 69], [29, 0.75, 67], [29.75, 0.25, 65],
  [30, 1, 67], [31, 0.5, 60], [31.5, 0.5, 60], [32, 1, 72],
  [33, 0.75, 71], [33.75, 0.25, 69], [34, 0.5, 67], [34.5, 0.5, 71],
  [35, 0.5, 72], [35.5, 0.5, 74], [36, 2, 76], [38, 0.5, 74],
  [38.5, 0.5, 72], [39, 0.5, 71], [39.5, 0.5, 72], [40, 1.5, 74],
  [41.5, 0.5, 67], [42, 0.5, 67], [42.5, 0.5, 71], [43, 0.5, 72],
  [43.5, 0.5, 74], [44, 2, 72], [46, 0.5, 71], [46.5, 0.5, 69],
  [47, 0.5, 67], [47.5, 0.5, 69], [48, 1.5, 71], [49.5, 0.5, 64],
  [50, 0.5, 64], [50.5, 0.5, 67], [51, 0.5, 69], [51.5, 0.5, 71],
  [52, 1, 72], [53, 0.75, 69], [53.75, 0.25, 71], [54, 1, 72],
  [55, 0.75, 69], [55.75, 0.25, 71], [56, 1, 72], [57, 0.5, 69],
  [57.5, 0.5, 72], [58, 2, 77], [60, 2, 77], [62, 0.5, 76],
  [62.5, 0.5, 74], [63, 0.5, 72], [63.5, 0.5, 74], [64, 1.5, 76],
  [65.5, 0.5, 72], [66, 2, 72], [68, 2, 74], [70, 0.5, 72],
  [70.5, 0.5, 71], [71, 0.5, 69], [71.5, 0.5, 71], [72, 1.5, 72],
  [73.5, 0.5, 69], [74, 2, 69], [76, 2, 67], [78, 0.2, 69],
  [78.11, 1, 71], [79.11, 2.5, 72]
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

  /* Зал: короткий импульсный отклик из затухающего шума — без внешних файлов. */
  function hallImpulse(seconds, decay) {
    var rate = ctx.sampleRate
    var length = Math.max(1, Math.floor(rate * seconds))
    var buffer = ctx.createBuffer(2, length, rate)
    for (var channel = 0; channel < 2; channel += 1) {
      var data = buffer.getChannelData(channel)
      for (var i = 0; i < length; i += 1) {
        var t = i / length
        data[i] = (Math.random() * 2 - 1) * Math.pow(1 - t, decay)
      }
    }
    return buffer
  }

  function build() {
    var AudioCtx = window.AudioContext || window.webkitAudioContext
    if (!AudioCtx) return false
    ctx = new AudioCtx()

    master = ctx.createGain()
    master.gain.value = 0.62

    var compressor = ctx.createDynamicsCompressor()
    compressor.threshold.value = -20
    compressor.knee.value = 24
    compressor.ratio.value = 3.2
    compressor.attack.value = 0.006
    compressor.release.value = 0.22

    master.connect(compressor)
    compressor.connect(ctx.destination)

    // Немного зала: соло без реверберации звучит как пищалка из открытки.
    var convolver = ctx.createConvolver()
    convolver.buffer = hallImpulse(2.4, 3.2)
    var wet = ctx.createGain()
    wet.gain.value = 0.32
    var dry = ctx.createGain()
    dry.gain.value = 1.0
    convolver.connect(wet)
    wet.connect(compressor)
    master.connect(dry)
    dry.connect(compressor)
    master.connect(convolver)
    return true
  }

  function filterOf(at, duration, freq) {
    var filter = ctx.createBiquadFilter()
    filter.type = 'lowpass'
    filter.Q.value = 0.9
    var open = Math.min(6000, freq * 7)
    filter.frequency.setValueAtTime(Math.min(open, freq * 2.6), at)
    filter.frequency.linearRampToValueAtTime(open, at + 0.07)
    filter.frequency.exponentialRampToValueAtTime(freq * 3.2, at + Math.max(0.2, duration))
    return filter
  }

  function note(freq, at, duration) {
    var filter = filterOf(at, duration, freq)
    var gain = ctx.createGain()

    var peak = 0.19
    var attack = 0.055
    var release = Math.min(0.16, duration * 0.35)
    gain.gain.setValueAtTime(0.0001, at)
    gain.gain.exponentialRampToValueAtTime(peak, at + attack)
    gain.gain.exponentialRampToValueAtTime(peak * 0.82, at + Math.min(attack * 3, 0.2))
    gain.gain.setValueAtTime(peak * 0.82, at + Math.max(attack * 3.2, duration - release))
    gain.gain.exponentialRampToValueAtTime(0.0001, at + duration)

    // Медь: два пилообразных голоса враздрай + треугольник, всё через один фильтр.
    ;[
      { type: 'sawtooth', detune: -6, level: 0.5 },
      { type: 'sawtooth', detune: 6, level: 0.35 },
      { type: 'triangle', detune: 0, level: 0.4 },
    ].forEach(function (item) {
      var osc = ctx.createOscillator()
      osc.type = item.type
      osc.frequency.value = freq
      osc.detune.value = item.detune
      var amp = ctx.createGain()
      amp.gain.value = item.level
      osc.connect(amp)
      amp.connect(filter)
      osc.start(at)
      osc.stop(at + duration + 0.12)

      if (duration > 0.9) {
        var lfo = ctx.createOscillator()
        var depth = ctx.createGain()
        lfo.frequency.value = 5.2
        depth.gain.value = freq * 0.004
        lfo.connect(depth)
        depth.connect(osc.frequency)
        lfo.start(at + 0.18)
        lfo.stop(at + duration + 0.1)
      }
    })

    // Октавой ниже — тело, иначе соло звенит.
    var bass = ctx.createOscillator()
    bass.type = 'triangle'
    bass.frequency.value = freq / 2
    var bassAmp = ctx.createGain()
    bassAmp.gain.value = 0.3
    bass.connect(bassAmp)
    bassAmp.connect(gain)
    bass.start(at)
    bass.stop(at + duration + 0.1)

    filter.connect(gain)
    gain.connect(master)
  }

  function play(button) {
    if (!ctx && !build()) {
      button.title = 'Браузер не умеет Web Audio — гимн сыграть нечем'
      return
    }
    if (ctx.state === 'suspended') ctx.resume()
    var start = ctx.currentTime + 0.2
    NOTES.forEach(function (item) {
      var beatStart = item[0]
      var beats = item[1]
      var midi = item[2]
      var freq = 440 * Math.pow(2, (midi - 69) / 12)
      note(freq, start + beatStart * BEAT, Math.max(0.16, beats * BEAT))
    })
    playing = true
    button.setAttribute('aria-pressed', 'true')
    button.querySelector('.kremle-anthem__label').textContent = 'остановить'
    button.querySelector('.kremle-anthem__icon').innerHTML = ICON_STOP
    button.title = 'Остановить гимн'

    var last = NOTES[NOTES.length - 1]
    var total = (last[0] + last[1]) * BEAT + 2.4
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
