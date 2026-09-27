#!/usr/bin/env node
// Summarize a completed Vite build without reading source maps or private runtime data.
import { createHash } from 'node:crypto'
import { readFile, readdir } from 'node:fs/promises'
import { join, relative, resolve } from 'node:path'
import { gzipSync } from 'node:zlib'

const projectRoot = resolve(import.meta.dirname, '..')
const distRoot = resolve(process.argv[2] || join(projectRoot, 'frontend', 'dist'))
const assets = []

async function walk(directory) {
  for (const item of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, item.name)
    if (item.isDirectory()) await walk(path)
    else if (item.isFile() && /\.(js|css)$/.test(item.name)) {
      const bytes = await readFile(path)
      assets.push({
        asset: relative(distRoot, path),
        kind: item.name.endsWith('.css') ? 'css' : 'js',
        raw_bytes: bytes.length,
        gzip_bytes: gzipSync(bytes, { level: 9 }).length,
        sha256: createHash('sha256').update(bytes).digest('hex'),
      })
    }
  }
}

await walk(distRoot)
assets.sort((a, b) => a.asset.localeCompare(b.asset))
const totals = { js: { raw_bytes: 0, gzip_bytes: 0 }, css: { raw_bytes: 0, gzip_bytes: 0 } }
for (const asset of assets) {
  totals[asset.kind].raw_bytes += asset.raw_bytes
  totals[asset.kind].gzip_bytes += asset.gzip_bytes
}
console.log(JSON.stringify({ schema: 'open-agronomy.frontend-build-profile.v1', assets, totals }, null, 2))
