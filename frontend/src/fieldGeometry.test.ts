import { describe, expect, it } from 'vitest'

import { estimatePolygonAcres, fieldGeometryIssue, polygonSelfIntersects } from './fieldGeometry'

describe('field geometry validity', () => {
  const rectangle = [
    { lat: 49.862, lon: -99.965 },
    { lat: 49.862, lon: -99.935 },
    { lat: 49.878, lon: -99.935 },
    { lat: 49.878, lon: -99.965 },
  ]

  it('accepts a simple field polygon', () => {
    expect(polygonSelfIntersects(rectangle)).toBe(false)
    expect(fieldGeometryIssue({ kind: 'polygon', points: rectangle, acres: estimatePolygonAcres(rectangle) })).toBeNull()
  })

  it('rejects a self-crossing field polygon', () => {
    const bowTie = [rectangle[0], rectangle[2], rectangle[1], rectangle[3]]
    expect(polygonSelfIntersects(bowTie)).toBe(true)
    expect(fieldGeometryIssue({ kind: 'polygon', points: bowTie, acres: estimatePolygonAcres(bowTie) })).toMatch(/edges cross/i)
  })

  it('keeps incomplete drafts out of intersect and save workflows', () => {
    expect(fieldGeometryIssue({ kind: 'polygon', points: rectangle.slice(0, 2), acres: 0 })).toMatch(/at least three/i)
  })
})
