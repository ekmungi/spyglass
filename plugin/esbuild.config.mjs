// esbuild bundler config for the Obsidian plugin. The canonical manifest lives
// at the repo root (BRAT requirement); it is copied into dist/ so the built
// folder is a self-contained, installable plugin.
import esbuild from 'esbuild'
import { copyFileSync } from 'node:fs'
import process from 'node:process'
import builtins from 'builtin-modules'

const production = process.argv[2] === 'production'

/** Copy the root manifest into dist so dist/ can be dropped into a vault as-is. */
function copyManifest() {
  copyFileSync('../manifest.json', 'dist/manifest.json')
}

const context = await esbuild.context({
  entryPoints: ['src/main.ts'],
  bundle: true,
  external: ['obsidian', 'electron', ...builtins],
  format: 'cjs',
  target: 'es2022',
  logLevel: 'info',
  sourcemap: production ? false : 'inline',
  treeShaking: true,
  outfile: 'dist/main.js',
})

if (production) {
  await context.rebuild()
  copyManifest()
  process.exit(0)
} else {
  await context.watch()
  copyManifest()
}
