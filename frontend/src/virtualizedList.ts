export const PHASE6_VIRTUAL_LIST_LIMIT = 50

export type Phase6VirtualListWindow<T> = {
  visibleItems: T[]
  totalCount: number
  visibleCount: number
  omittedCount: number
  isWindowed: boolean
}

export function virtualizePhase6List<T>(items: readonly T[], limit = PHASE6_VIRTUAL_LIST_LIMIT): Phase6VirtualListWindow<T> {
  if (!Number.isInteger(limit) || limit < 1) {
    throw new Error('virtual list limit must be a positive integer')
  }
  const visibleItems = items.slice(0, limit)
  return {
    visibleItems,
    totalCount: items.length,
    visibleCount: visibleItems.length,
    omittedCount: Math.max(0, items.length - visibleItems.length),
    isWindowed: items.length > visibleItems.length,
  }
}
