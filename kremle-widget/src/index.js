/**
 * Публичный API ванильного виджета.
 *
 * ESM: `import { mount } from 'kremle-widget'`
 * IIFE: `KremleWidget.mount('#kremle')` — без сборки, одним `<script>`.
 */
export { autoMount, createWidget, mount, resultMessage } from './widget.js'
export { collectFingerprint } from './fingerprint.js'
