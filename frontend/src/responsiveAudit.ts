export type ResponsiveAuditViolation = {
  ruleId: string
  message: string
  selector?: string
}

export type ResponsiveAuditReport = {
  schemaVersion: 'phase6.frontend_responsive_audit.v1'
  auditedAt: string
  checkedRules: string[]
  viewportWidths: number[]
  viewportProfiles: ResponsiveViewportProfile[]
  violationCount: number
  violations: ResponsiveAuditViolation[]
  passed: boolean
}

export type ResponsiveViewportProfile = {
  id: 'mobile' | 'tablet' | 'desktop'
  targetWidth: number
  minWidth: number
  maxWidth: number | null
  requiredSurfaces: string[]
}

const CHECKED_RULES = [
  'desktop-tablet-mobile-matrix',
  'mobile-breakpoint-present',
  'mobile-touch-targets',
  'mobile-full-width-controls',
  'mobile-public-nav-targets',
  'primary-flow-surfaces-present',
  'overflow-wrap-boundaries',
]

const REQUIRED_PRIMARY_SURFACES = [
  'public-demo-pages',
  'hosted-platform',
  'hosted-local-preview',
  'hosted-field-context',
  'hosted-evidence-panel',
  'hosted-export-type-filter',
  'hosted-export',
  'hosted-user',
  'hosted-export-account',
]

export const PHASE6_RESPONSIVE_VIEWPORT_MATRIX: ResponsiveViewportProfile[] = [
  {
    id: 'mobile',
    targetWidth: 375,
    minWidth: 320,
    maxWidth: 480,
    requiredSurfaces: ['hosted-platform', 'hosted-field-context', 'hosted-evidence-panel', 'hosted-export'],
  },
  {
    id: 'tablet',
    targetWidth: 768,
    minWidth: 700,
    maxWidth: 1024,
    requiredSurfaces: ['public-demo-pages', 'hosted-platform', 'hosted-local-preview', 'hosted-evidence-panel'],
  },
  {
    id: 'desktop',
    targetWidth: 1120,
    minWidth: 1025,
    maxWidth: null,
    requiredSurfaces: ['public-demo-pages', 'hosted-platform', 'hosted-export-account', 'hosted-export'],
  },
]

export function auditPhase6ResponsiveReadiness(
  root: ParentNode = document,
  cssText = '',
  viewportWidths = PHASE6_RESPONSIVE_VIEWPORT_MATRIX.map((profile) => profile.targetWidth),
): ResponsiveAuditReport {
  const violations: ResponsiveAuditViolation[] = []
  const normalizedCss = normalizeCss(cssText)
  const mobileCss = mobileMediaBlocks(normalizedCss).join('\n')

  for (const profile of PHASE6_RESPONSIVE_VIEWPORT_MATRIX) {
    if (!viewportWidths.some((width) => width >= profile.minWidth && (profile.maxWidth === null || width <= profile.maxWidth))) {
      violations.push({
        ruleId: 'desktop-tablet-mobile-matrix',
        message: `Responsive QA must include a ${profile.id} viewport around ${profile.targetWidth}px.`,
      })
    }
    for (const testId of profile.requiredSurfaces) {
      if (!root.querySelector(`[data-testid="${testId}"]`)) {
        violations.push({
          ruleId: 'desktop-tablet-mobile-matrix',
          message: `${profile.id} viewport QA surface is missing: ${testId}.`,
          selector: `[data-testid="${testId}"]`,
        })
      }
    }
  }

  if (!mobileCss) {
    violations.push({
      ruleId: 'mobile-breakpoint-present',
      message: 'CSS must include a max-width mobile breakpoint for the 375px launch QA target.',
    })
  }

  if (!/button\s*,\s*input\s*,\s*select\s*\{[^}]*min-height\s*:\s*44px/.test(mobileCss)) {
    violations.push({
      ruleId: 'mobile-touch-targets',
      message: 'Mobile breakpoint must set button/input/select touch targets to at least 44px.',
      selector: 'button,input,select',
    })
  }

  if (!/button\s*,\s*input\s*,\s*select\s*\{[^}]*width\s*:\s*100%/.test(mobileCss)) {
    violations.push({
      ruleId: 'mobile-full-width-controls',
      message: 'Mobile breakpoint must make core controls full-width to avoid cramped rows at 375px.',
      selector: 'button,input,select',
    })
  }

  if (!/nav\s+a\s*\{[^}]*min-height\s*:\s*44px/.test(mobileCss)) {
    violations.push({
      ruleId: 'mobile-touch-targets',
      message: 'Mobile public navigation links must have 44px touch targets.',
      selector: 'nav a',
    })
  }

  const publicNavLinks = Array.from(root.querySelectorAll('[data-testid="public-demo-pages"] nav a[href]'))
  if (publicNavLinks.length < 8 || publicNavLinks.some((link) => !link.textContent?.trim())) {
    violations.push({
      ruleId: 'mobile-public-nav-targets',
      message: 'Public demo pages need named in-page navigation targets for compact screens.',
      selector: '[data-testid="public-demo-pages"] nav a[href]',
    })
  }

  for (const testId of REQUIRED_PRIMARY_SURFACES) {
    if (!root.querySelector(`[data-testid="${testId}"]`)) {
      violations.push({
        ruleId: 'primary-flow-surfaces-present',
        message: `Primary mobile QA surface is missing: ${testId}.`,
        selector: `[data-testid="${testId}"]`,
      })
    }
  }

  for (const selector of ['section', '.answer-panel', '.evidence-panel', 'pre']) {
    if (!ruleForSelectorHasAny(normalizedCss, selector, ['overflow-wrap: anywhere', 'overflow: auto', 'min-width: 0'])) {
      violations.push({
        ruleId: 'overflow-wrap-boundaries',
        message: `Responsive CSS must prevent horizontal overflow for ${selector}.`,
        selector,
      })
    }
  }

  return {
    schemaVersion: 'phase6.frontend_responsive_audit.v1',
    auditedAt: new Date().toISOString(),
    checkedRules: CHECKED_RULES,
    viewportWidths,
    viewportProfiles: PHASE6_RESPONSIVE_VIEWPORT_MATRIX,
    violationCount: violations.length,
    violations,
    passed: violations.length === 0,
  }
}

function normalizeCss(cssText: string): string {
  return cssText.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\s+/g, ' ').trim()
}

function mobileMediaBlocks(cssText: string): string[] {
  const blocks: string[] = []
  const mediaPattern = /@media\s*\((max-width|min-width)\s*:\s*(\d+)px\)\s*\{/g
  let match: RegExpExecArray | null
  while ((match = mediaPattern.exec(cssText)) !== null) {
    const kind = match[1]
    const width = Number(match[2])
    if (kind !== 'max-width' || width > 780) {
      continue
    }
    const blockStart = mediaPattern.lastIndex
    const blockEnd = findMatchingBrace(cssText, blockStart - 1)
    if (blockEnd > blockStart) {
      blocks.push(cssText.slice(blockStart, blockEnd))
    }
  }
  return blocks
}

function findMatchingBrace(text: string, openBraceIndex: number): number {
  let depth = 0
  for (let index = openBraceIndex; index < text.length; index += 1) {
    if (text[index] === '{') {
      depth += 1
    } else if (text[index] === '}') {
      depth -= 1
      if (depth === 0) {
        return index
      }
    }
  }
  return -1
}

function ruleForSelectorHasAny(cssText: string, selector: string, properties: string[]): boolean {
  const rulePattern = /([^{}@]+)\{([^{}]+)\}/g
  let match: RegExpExecArray | null
  while ((match = rulePattern.exec(cssText)) !== null) {
    const selectors = match[1].split(',').map((item) => item.trim())
    const body = match[2].replace(/\s+/g, ' ').trim()
    if (selectors.includes(selector) && properties.some((property) => body.includes(property))) {
      return true
    }
  }
  return false
}
