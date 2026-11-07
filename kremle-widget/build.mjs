/**
 * Сборка виджета: ESM для сборщиков и IIFE для `<script src>`.
 *
 * Отдельного конфига нет намеренно: две строки esbuild проще, чем ещё один
 * инструмент в зависимостях.
 */
import { build } from 'esbuild'

const shared = {
  entryPoints: ['src/index.js'],
  bundle: true,
  target: ['es2018'],
  sourcemap: true,
  logLevel: 'info',
}

await build({
  ...shared,
  format: 'esm',
  outfile: 'dist/kremle-widget.mjs',
})

await build({
  ...shared,
  format: 'iife',
  globalName: 'KremleWidget',
  outfile: 'dist/kremle-widget.js',
})

await build({
  ...shared,
  format: 'iife',
  globalName: 'KremleWidget',
  minify: true,
  sourcemap: false,
  outfile: 'dist/kremle-widget.min.js',
})
