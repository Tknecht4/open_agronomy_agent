export type RenderingSecurityIssue = {
  surface: string
  reason: string
}

const LAUNCH_SURFACES = [
  'hosted-answer-panel',
  'hosted-evidence-panel',
  'turn-list',
  'evidence-browser',
  'public-demo-pages',
]

const ACTIVE_ELEMENT_SELECTORS = [
  'script',
  'iframe',
  'object',
  'embed',
  'style',
  'meta[http-equiv="refresh"]',
  'link[rel="import"]',
]

const URL_ATTRIBUTES = ['href', 'src', 'action', 'formaction', 'xlink:href']
const UNSAFE_DATA_URL_RE = /^data:(text\/html|image\/svg\+xml|application\/xhtml\+xml|application\/xml|text\/xml)(?:[;,]|$)/

export const auditPhase6RenderingSecurity = (root: ParentNode = document): RenderingSecurityIssue[] => {
  const issues: RenderingSecurityIssue[] = []
  for (const testId of LAUNCH_SURFACES) {
    const surface = findByTestId(root, testId)
    if (!surface) {
      continue
    }
    for (const selector of ACTIVE_ELEMENT_SELECTORS) {
      if (surface.querySelector(selector)) {
        issues.push({ surface: testId, reason: `active element rendered: ${selector}` })
      }
    }
    surface.querySelectorAll('*').forEach((element) => {
      for (const attribute of Array.from(element.attributes)) {
        const name = attribute.name.toLowerCase()
        const value = attribute.value.trim().toLowerCase()
        if (name.startsWith('on')) {
          issues.push({ surface: testId, reason: `event handler attribute rendered: ${name}` })
        }
        if (URL_ATTRIBUTES.includes(name) && isUnsafeLaunchUrl(value)) {
          issues.push({ surface: testId, reason: `unsafe URL attribute rendered: ${name}` })
        }
      }
    })
  }
  return issues
}

const isUnsafeLaunchUrl = (rawValue: string): boolean => {
  const value = rawValue.trim().toLowerCase()
  const compactValue = value.replace(/[\u0000-\u001f\u007f\s]+/g, '')
  if (compactValue.startsWith('javascript:') || compactValue.startsWith('vbscript:')) {
    return true
  }
  return UNSAFE_DATA_URL_RE.test(compactValue)
}

const findByTestId = (root: ParentNode, testId: string): Element | null => {
  if (root instanceof Element && root.getAttribute('data-testid') === testId) {
    return root
  }
  return root.querySelector(`[data-testid="${testId}"]`)
}
