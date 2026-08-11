import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { phase6DesignTokens, requiredPhase6SemanticColorTokens } from './designTokens'

const css = readFileSync('src/design-tokens.css', 'utf-8')
const styles = readFileSync('src/styles.css', 'utf-8')

const cssVariable = (name: string) => {
  const match = css.match(new RegExp(`--${name}:\\s*([^;]+);`))
  return match?.[1]?.trim()
}

describe('Phase 6 design tokens', () => {
  it('publishes the required semantic color system from the packet', () => {
    for (const token of requiredPhase6SemanticColorTokens) {
      expect(phase6DesignTokens.color[token]).toMatch(/^#[0-9a-f]{6}$/i)
      const cssName = token.replace(/[A-Z]/g, (char) => `-${char.toLowerCase()}`)
      expect(cssVariable(`phase6-color-${cssName}`)).toBe(phase6DesignTokens.color[token])
    }
  })

  it('keeps one typography scale in TypeScript and CSS', () => {
    expect(cssVariable('phase6-font-family')).toBe(phase6DesignTokens.typography.family)
    expect(cssVariable('phase6-font-size-body')).toBe(phase6DesignTokens.typography.sizeBody)
    expect(cssVariable('phase6-font-size-heading')).toBe(phase6DesignTokens.typography.sizeHeading)
    expect(cssVariable('phase6-font-size-subheading')).toBe(phase6DesignTokens.typography.sizeSubheading)
    expect(cssVariable('phase6-line-height-tight')).toBe(phase6DesignTokens.typography.lineHeightTight)
  })

  it('loads token variables before app styles use them', () => {
    expect(styles).toContain("@import './design-tokens.css';")
    expect(styles).toContain('font-family: var(--phase6-font-family)')
    expect(styles).toContain('background: var(--phase6-color-page)')
    expect(styles).toContain('color: var(--phase6-color-text)')
  })
})
