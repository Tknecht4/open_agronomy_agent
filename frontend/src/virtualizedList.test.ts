import { describe, expect, it } from 'vitest'
import { PHASE6_VIRTUAL_LIST_LIMIT, virtualizePhase6List } from './virtualizedList'

describe('Phase 6 virtual list windows', () => {
  it('returns all items when the list is inside the render budget', () => {
    const windowed = virtualizePhase6List(['a', 'b'], 5)

    expect(windowed).toEqual({
      visibleItems: ['a', 'b'],
      totalCount: 2,
      visibleCount: 2,
      omittedCount: 0,
      isWindowed: false,
    })
  })

  it('caps large lists and reports omitted rows explicitly', () => {
    const items = Array.from({ length: PHASE6_VIRTUAL_LIST_LIMIT + 3 }, (_, index) => index)
    const windowed = virtualizePhase6List(items)

    expect(windowed.visibleItems).toHaveLength(PHASE6_VIRTUAL_LIST_LIMIT)
    expect(windowed.visibleItems[0]).toBe(0)
    expect(windowed.visibleItems.at(-1)).toBe(PHASE6_VIRTUAL_LIST_LIMIT - 1)
    expect(windowed.totalCount).toBe(PHASE6_VIRTUAL_LIST_LIMIT + 3)
    expect(windowed.omittedCount).toBe(3)
    expect(windowed.isWindowed).toBe(true)
  })

  it('fails loudly for invalid limits', () => {
    expect(() => virtualizePhase6List([1], 0)).toThrow('positive integer')
    expect(() => virtualizePhase6List([1], 1.5)).toThrow('positive integer')
  })
})
