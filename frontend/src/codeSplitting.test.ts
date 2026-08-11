import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

describe('Phase 6 route-level code splitting', () => {
  it('keeps heavy launch surfaces behind React lazy imports', () => {
    const appSource = readFileSync('src/App.tsx', 'utf-8')

    expect(appSource).toContain("lazy(() => import('./HostedPlatform')")
    expect(appSource).toContain("lazy(() => import('./PublicDemoPages')")
    expect(appSource).toContain('<Suspense')
    expect(appSource).not.toContain("import { HostedPlatform } from './HostedPlatform'")
    expect(appSource).not.toContain("import { PublicDemoPages } from './PublicDemoPages'")
  })
})
