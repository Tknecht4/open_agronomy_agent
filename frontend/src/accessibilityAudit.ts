export type AccessibilityViolation = {
  ruleId: string
  message: string
  selector: string
  text?: string
}

export type AccessibilityAuditReport = {
  schemaVersion: 'phase6.frontend_accessibility_audit.v1'
  auditedAt: string
  checkedRules: string[]
  elementCount: number
  violationCount: number
  violations: AccessibilityViolation[]
  passed: boolean
}

const CHECKED_RULES = [
  'button-name',
  'form-control-name',
  'link-name',
  'image-alt',
  'no-positive-tabindex',
  'duplicate-id',
  'heading-order',
]

export function auditPhase6Accessibility(root: ParentNode = document): AccessibilityAuditReport {
  const violations: AccessibilityViolation[] = []
  const rootElement = root instanceof Document ? root.documentElement : root

  for (const element of Array.from(root.querySelectorAll('button'))) {
    if (!accessibleName(element)) {
      violations.push(violation('button-name', 'Button has no accessible name.', element))
    }
  }

  for (const element of Array.from(root.querySelectorAll('input, select, textarea'))) {
    const input = element as HTMLInputElement
    if (input.type === 'hidden') {
      continue
    }
    if (!accessibleName(element)) {
      violations.push(violation('form-control-name', 'Form control has no accessible name.', element))
    }
  }

  for (const element of Array.from(root.querySelectorAll('a[href]'))) {
    if (!accessibleName(element)) {
      violations.push(violation('link-name', 'Link has no accessible name.', element))
    }
  }

  for (const element of Array.from(root.querySelectorAll('img'))) {
    if (!element.hasAttribute('alt')) {
      violations.push(violation('image-alt', 'Image is missing alt text.', element))
    }
  }

  for (const element of Array.from(root.querySelectorAll('[tabindex]'))) {
    const tabindex = Number(element.getAttribute('tabindex'))
    if (Number.isFinite(tabindex) && tabindex > 0) {
      violations.push(violation('no-positive-tabindex', 'Positive tabindex disrupts keyboard navigation order.', element))
    }
  }

  const seenIds = new Map<string, Element>()
  for (const element of Array.from(root.querySelectorAll('[id]'))) {
    const id = element.id.trim()
    if (!id) {
      continue
    }
    if (seenIds.has(id)) {
      violations.push(violation('duplicate-id', `Duplicate id "${id}" breaks label and aria references.`, element))
    } else {
      seenIds.set(id, element)
    }
  }

  let previousHeadingLevel = 0
  for (const heading of Array.from(root.querySelectorAll('h1, h2, h3, h4, h5, h6'))) {
    const level = Number(heading.tagName.slice(1))
    if (previousHeadingLevel > 0 && level > previousHeadingLevel + 1) {
      violations.push(violation('heading-order', `Heading level jumps from h${previousHeadingLevel} to h${level}.`, heading))
    }
    previousHeadingLevel = level
  }

  return {
    schemaVersion: 'phase6.frontend_accessibility_audit.v1',
    auditedAt: new Date().toISOString(),
    checkedRules: CHECKED_RULES,
    elementCount: rootElement instanceof Element ? rootElement.querySelectorAll('*').length : root.querySelectorAll('*').length,
    violationCount: violations.length,
    violations,
    passed: violations.length === 0,
  }
}

function accessibleName(element: Element): string {
  const ariaLabel = element.getAttribute('aria-label')?.trim()
  if (ariaLabel) {
    return ariaLabel
  }
  const labelledBy = element.getAttribute('aria-labelledby')
  if (labelledBy) {
    const text = labelledBy
      .split(/\s+/)
      .map((id) => element.ownerDocument.getElementById(id)?.textContent?.trim() || '')
      .filter(Boolean)
      .join(' ')
      .trim()
    if (text) {
      return text
    }
  }
  if (element instanceof HTMLInputElement && ['button', 'submit', 'reset'].includes(element.type) && element.value.trim()) {
    return element.value.trim()
  }
  const id = element.getAttribute('id')
  if (id) {
    const label = element.ownerDocument.querySelector(`label[for="${cssEscape(id)}"]`)
    if (label?.textContent?.trim()) {
      return label.textContent.trim()
    }
  }
  const wrappingLabel = element.closest('label')
  if (wrappingLabel?.textContent?.trim()) {
    return wrappingLabel.textContent.trim()
  }
  const title = element.getAttribute('title')?.trim()
  if (title) {
    return title
  }
  return element.textContent?.trim() || ''
}

function violation(ruleId: string, message: string, element: Element): AccessibilityViolation {
  return {
    ruleId,
    message,
    selector: selectorFor(element),
    text: element.textContent?.trim().replace(/\s+/g, ' ').slice(0, 120),
  }
}

function selectorFor(element: Element): string {
  const testId = element.getAttribute('data-testid')
  if (testId) {
    return `[data-testid="${testId}"]`
  }
  if (element.id) {
    return `#${element.id}`
  }
  const tag = element.tagName.toLowerCase()
  const parent = element.parentElement
  if (!parent) {
    return tag
  }
  const siblings = Array.from(parent.children).filter((item) => item.tagName === element.tagName)
  if (siblings.length <= 1) {
    return tag
  }
  return `${tag}:nth-of-type(${siblings.indexOf(element) + 1})`
}

function cssEscape(value: string): string {
  if (typeof CSS !== 'undefined' && typeof CSS.escape === 'function') {
    return CSS.escape(value)
  }
  return value.replace(/["\\]/g, '\\$&')
}
