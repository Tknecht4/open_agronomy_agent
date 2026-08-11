import { describe, expect, it } from 'vitest'
import { auditPhase6RenderingSecurity } from './renderingSecurityAudit'

describe('auditPhase6RenderingSecurity', () => {
  it('passes when hostile markup appears as escaped text', () => {
    document.body.innerHTML = `
      <section data-testid="hosted-answer-panel">
        &lt;script&gt;alert('x')&lt;/script&gt;&lt;img src=x onerror=alert(1)&gt;
      </section>
      <section data-testid="hosted-evidence-panel">
        javascript:alert(1)
        data:image/svg+xml,&lt;svg onload=alert(1)&gt;
      </section>
    `

    expect(auditPhase6RenderingSecurity()).toEqual([])
  })

  it('fails closed on active elements, event handlers, and unsafe URLs in launch surfaces', () => {
    document.body.innerHTML = `
      <section data-testid="hosted-answer-panel">
        <script>alert('x')</script>
        <a href="java
          script:alert(1)">bad</a>
      </section>
      <section data-testid="hosted-evidence-panel">
        <img src="/ok.png" onerror="alert(1)">
      </section>
      <section data-testid="public-demo-pages">
        <a href="vbscript:alert(1)">legacy bad</a>
        <img src="data:image/svg+xml,<svg onload=alert(1)>">
      </section>
    `

    expect(auditPhase6RenderingSecurity()).toEqual([
      { surface: 'hosted-answer-panel', reason: 'active element rendered: script' },
      { surface: 'hosted-answer-panel', reason: 'unsafe URL attribute rendered: href' },
      { surface: 'hosted-evidence-panel', reason: 'event handler attribute rendered: onerror' },
      { surface: 'public-demo-pages', reason: 'unsafe URL attribute rendered: href' },
      { surface: 'public-demo-pages', reason: 'unsafe URL attribute rendered: src' },
    ])
  })
})
