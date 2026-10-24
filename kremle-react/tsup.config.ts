import { defineConfig } from 'tsup'

export default defineConfig({
  entry: ['src/index.ts'],
  format: ['cjs', 'esm'],
  // .d.ts собирает tsc из tsconfig.build.json: в TypeScript 7 (нативная
  // версия) нет JS-компилятора, на котором держится dts-плагин tsup.
  dts: false,
  clean: true,
  external: ['react', 'react-dom', 'react/jsx-runtime'],
  sourcemap: true,
  // 'use client' не нужен: компонент сам по себе SSR-safe, но в Next.js
  // app router его всё равно импортируют из клиентского файла.
  banner: { js: "'use client'" },
})
