import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import type { Plugin } from 'vite'

/** Pin the shell and every lazy dependency to the same production build. */
export function workspaceServiceWorker(): Plugin {
  let publicDirectory: string
  return {
    name: 'workspace-service-worker',
    enforce: 'post',
    configResolved(config) { publicDirectory = config.publicDir },
    generateBundle(_options, bundle) {
      const source = readFileSync(resolve(publicDirectory, 'service-worker.js'), 'utf8')
      const hash = createHash('sha256').update(source)
      // Vite copies public files without including them in the Rollup bundle.
      // Fixed cache URLs must still invalidate the worker when their bytes change.
      for (const name of ['offline.html', 'manifest.webmanifest', 'icons/agronomy-agent.svg']) {
        hash.update(name).update(readFileSync(resolve(publicDirectory, name)))
      }
      for (const [name, output] of Object.entries(bundle).sort(([left], [right]) => left.localeCompare(right))) {
        hash.update(name).update(output.type === 'chunk' ? output.code : output.source)
      }
      const assets = Object.keys(bundle).filter(name => name.startsWith('assets/')).sort().map(name => `/${name}`)
      const index = bundle['index.html']
      if (!index || index.type !== 'asset') this.error('The workspace index is missing from the build.')
      const shellAssets = Array.from(String(index.source).matchAll(/(?:src|href)=["'](\/assets\/[^"']+)["']/g), match => match[1])
      this.emitFile({
        type: 'asset',
        fileName: 'service-worker.js',
        source: source.replace("const BUILD_ID = 'unbuilt'", `const BUILD_ID = '${hash.digest('hex').slice(0, 16)}'`)
          .replace('const BUILD_ASSETS = []', `const BUILD_ASSETS = ${JSON.stringify(assets)}`)
          .replace('const BUILD_SHELL_ASSETS = []', `const BUILD_SHELL_ASSETS = ${JSON.stringify(shellAssets)}`),
      })
    },
  }
}
