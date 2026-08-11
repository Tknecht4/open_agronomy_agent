import { describe, expect, it } from 'vitest'
import { auditPhase6Accessibility } from './accessibilityAudit'

describe('auditPhase6Accessibility', () => {
  it('fails closed on unlabeled controls and unnamed buttons', () => {
    document.body.innerHTML = `
      <main>
        <h1>Audit fixture</h1>
        <button></button>
        <input />
        <a href="/empty"></a>
        <img src="/field.png" />
        <button tabindex="3">Jump</button>
      </main>
    `

    const report = auditPhase6Accessibility(document)

    expect(report.passed).toBe(false)
    expect(report.violations.map((item) => item.ruleId)).toEqual(
      expect.arrayContaining(['button-name', 'form-control-name', 'link-name', 'image-alt', 'no-positive-tabindex']),
    )
  })

  it('passes labeled controls and ordinary heading order', () => {
    document.body.innerHTML = `
      <main>
        <h1>Audit fixture</h1>
        <section>
          <h2>Form</h2>
          <label>Question <textarea></textarea></label>
          <label for="mode">Mode</label>
          <select id="mode"><option>mock</option></select>
          <button type="button">Send</button>
          <a href="#help">Help</a>
          <img src="/field.png" alt="" />
        </section>
      </main>
    `

    const report = auditPhase6Accessibility(document)

    expect(report.passed).toBe(true)
    expect(report.violations).toEqual([])
  })
})
