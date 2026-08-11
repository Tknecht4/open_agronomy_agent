import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { auditPhase6ResponsiveReadiness } from './responsiveAudit'

const REQUIRED_DOM = `
  <main>
    <section data-testid="public-demo-pages">
      <nav>
        <a href="#landing">Landing</a>
        <a href="#how-it-works">How It Works</a>
        <a href="#what-it-is-not">What It Is Not</a>
        <a href="#source-coverage">Data Source Coverage</a>
        <a href="#known-limitations">Known Limitations</a>
        <a href="#prompt-library">Prompt Library</a>
        <a href="#sample-reports">Sample Reports</a>
        <a href="#privacy-data-use">Privacy and Data Use</a>
      </nav>
    </section>
    <section data-testid="hosted-platform"></section>
    <section data-testid="hosted-local-preview"></section>
    <section data-testid="hosted-field-context"></section>
    <section data-testid="hosted-evidence-panel"></section>
    <select data-testid="hosted-export-type-filter"></select>
    <button data-testid="hosted-export">Export</button>
    <p data-testid="hosted-user">advisor@example.test</p>
    <button data-testid="hosted-export-account">Export account</button>
  </main>
`

const PASSING_CSS = `
  section { min-width: 0; overflow-wrap: anywhere; }
  .answer-panel, .evidence-panel { overflow-wrap: anywhere; }
  pre, [data-testid='trace-artifacts'] { overflow: auto; }
  @media (max-width: 720px) {
    button, input, select { width: 100%; min-height: 44px; }
    nav a { width: 100%; min-height: 44px; }
  }
`

describe('Phase 6 responsive audit', () => {
  it('passes when mobile launch surfaces, touch targets, and overflow guards are present', () => {
    const doc = document.implementation.createHTMLDocument('responsive-pass')
    doc.body.innerHTML = REQUIRED_DOM

    const report = auditPhase6ResponsiveReadiness(doc, PASSING_CSS, [375, 768, 1120])

    expect(report).toMatchObject({
      schemaVersion: 'phase6.frontend_responsive_audit.v1',
      passed: true,
      violationCount: 0,
      viewportWidths: [375, 768, 1120],
    })
    expect(report.viewportProfiles.map((profile) => profile.id)).toEqual(['mobile', 'tablet', 'desktop'])
  })

  it('fails closed when mobile breakpoint and required launch surfaces are missing', () => {
    const doc = document.implementation.createHTMLDocument('responsive-fail')
    doc.body.innerHTML = '<main><section data-testid="public-demo-pages"><nav><a href="#landing">Landing</a></nav></section></main>'

    const report = auditPhase6ResponsiveReadiness(doc, 'section { display: block; }')

    expect(report.passed).toBe(false)
    expect(report.violations.map((item) => item.ruleId)).toEqual(
      expect.arrayContaining([
        'mobile-breakpoint-present',
        'desktop-tablet-mobile-matrix',
        'mobile-touch-targets',
        'mobile-full-width-controls',
        'mobile-public-nav-targets',
        'primary-flow-surfaces-present',
        'overflow-wrap-boundaries',
      ]),
    )
  })

  it('fails closed when tablet or desktop viewport coverage is omitted', () => {
    const doc = document.implementation.createHTMLDocument('responsive-width-fail')
    doc.body.innerHTML = REQUIRED_DOM

    const report = auditPhase6ResponsiveReadiness(doc, PASSING_CSS, [375])

    expect(report.passed).toBe(false)
    expect(report.violations).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          ruleId: 'desktop-tablet-mobile-matrix',
          message: 'Responsive QA must include a tablet viewport around 768px.',
        }),
        expect.objectContaining({
          ruleId: 'desktop-tablet-mobile-matrix',
          message: 'Responsive QA must include a desktop viewport around 1120px.',
        }),
      ]),
    )
  })

  it('keeps public navigation links at touch-review size outside the mobile breakpoint', () => {
    const css = readFileSync('src/styles.css', 'utf-8').replace(/\s+/g, ' ')

    expect(css).toMatch(/nav a\s*\{[^}]*min-height:\s*44px/)
  })
})
