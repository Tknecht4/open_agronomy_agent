// @vitest-environment node
import { mkdtempSync, mkdirSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { build } from 'vite'
import { expect, it } from 'vitest'
import { workspaceServiceWorker } from '../workspaceServiceWorker'

it('installs a new worker when any fixed public cache asset changes', async () => {
  const root = realpathSync(mkdtempSync(join(tmpdir(), 'workspace-worker-build-')))
  try {
    mkdirSync(join(root, 'public/icons'), { recursive: true })
    writeFileSync(join(root, 'index.html'), '<script type="module" src="/main.js"></script>')
    writeFileSync(join(root, 'main.js'), 'document.title = "Workspace"')
    writeFileSync(join(root, 'public/service-worker.js'), readFileSync('public/service-worker.js'))
    const publicAssets = ['offline.html', 'manifest.webmanifest', 'icons/agronomy-agent.svg']
    publicAssets.forEach(name => writeFileSync(join(root, 'public', name), 'original bytes'))
    const builtWorker = async () => {
      await build({ root, configFile: false, logLevel: 'silent', plugins: [workspaceServiceWorker()] })
      return readFileSync(join(root, 'dist/service-worker.js'), 'utf8')
    }
    let previous = await builtWorker()
    expect(await builtWorker()).toBe(previous)
    for (const name of publicAssets) {
      writeFileSync(join(root, 'public', name), 'updated bytes')
      const updated = await builtWorker()
      expect(updated).not.toBe(previous)
      previous = updated
    }
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})
