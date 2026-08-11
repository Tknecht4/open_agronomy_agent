export type MapMode = 'inspect' | 'point' | 'boundary' | 'edit'

export type FieldPoint = {
  lat: number
  lon: number
}

export type FieldGeometry =
  | { kind: 'none' }
  | { kind: 'point'; point: FieldPoint }
  | { kind: 'polygon'; points: FieldPoint[]; acres: number }

export const estimatePolygonAcres = (points: FieldPoint[]): number => {
  if (points.length < 3) {
    return 0
  }
  const meanLat = points.reduce((sum, point) => sum + point.lat, 0) / points.length
  const metersPerDegreeLat = 111_320
  const metersPerDegreeLon = Math.cos((meanLat * Math.PI) / 180) * 111_320
  const projected = points.map((point) => ({
    x: point.lon * metersPerDegreeLon,
    y: point.lat * metersPerDegreeLat,
  }))
  const squareMeters = Math.abs(
    projected.reduce((sum, point, index) => {
      const next = projected[(index + 1) % projected.length]
      return sum + point.x * next.y - next.x * point.y
    }, 0) / 2,
  )
  return squareMeters / 4046.8564224
}

const orientation = (a: FieldPoint, b: FieldPoint, c: FieldPoint): number =>
  (b.lon - a.lon) * (c.lat - a.lat) - (b.lat - a.lat) * (c.lon - a.lon)

const pointOnSegment = (a: FieldPoint, b: FieldPoint, point: FieldPoint): boolean => {
  const epsilon = 1e-12
  return (
    Math.abs(orientation(a, b, point)) <= epsilon &&
    point.lon >= Math.min(a.lon, b.lon) - epsilon &&
    point.lon <= Math.max(a.lon, b.lon) + epsilon &&
    point.lat >= Math.min(a.lat, b.lat) - epsilon &&
    point.lat <= Math.max(a.lat, b.lat) + epsilon
  )
}

const segmentsIntersect = (a: FieldPoint, b: FieldPoint, c: FieldPoint, d: FieldPoint): boolean => {
  const epsilon = 1e-12
  const abC = orientation(a, b, c)
  const abD = orientation(a, b, d)
  const cdA = orientation(c, d, a)
  const cdB = orientation(c, d, b)
  if (
    ((abC > epsilon && abD < -epsilon) || (abC < -epsilon && abD > epsilon)) &&
    ((cdA > epsilon && cdB < -epsilon) || (cdA < -epsilon && cdB > epsilon))
  ) {
    return true
  }
  return (
    pointOnSegment(a, b, c) ||
    pointOnSegment(a, b, d) ||
    pointOnSegment(c, d, a) ||
    pointOnSegment(c, d, b)
  )
}

export const polygonSelfIntersects = (points: FieldPoint[]): boolean => {
  if (points.length < 4) {
    return false
  }
  const segmentCount = points.length
  for (let left = 0; left < segmentCount; left += 1) {
    const leftNext = (left + 1) % segmentCount
    for (let right = left + 1; right < segmentCount; right += 1) {
      const rightNext = (right + 1) % segmentCount
      if (leftNext === right || rightNext === left) {
        continue
      }
      if (segmentsIntersect(points[left], points[leftNext], points[right], points[rightNext])) {
        return true
      }
    }
  }
  return false
}

export const fieldGeometryIssue = (geometry: FieldGeometry): string | null => {
  if (geometry.kind === 'none') {
    return 'Add a point or draw a boundary first.'
  }
  if (geometry.kind === 'point') {
    return null
  }
  if (geometry.points.length < 3) {
    return 'Add at least three boundary vertices.'
  }
  if (polygonSelfIntersects(geometry.points)) {
    return 'Boundary edges cross. Edit the vertices before intersecting or saving.'
  }
  if (geometry.acres <= 0) {
    return 'Boundary vertices must enclose an area.'
  }
  return null
}

export const isUsableFieldGeometry = (geometry: FieldGeometry): boolean => fieldGeometryIssue(geometry) === null
