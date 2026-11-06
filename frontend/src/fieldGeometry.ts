export type MapMode = 'inspect' | 'point' | 'boundary' | 'edit'

export type FieldPoint = {
  lat: number
  lon: number
}

export type CompleteBoundary = { type: 'Polygon'; coordinates: number[][][] } | { type: 'MultiPolygon'; coordinates: number[][][][] }

export type FieldGeometry =
  | { kind: 'none' }
  | { kind: 'geojson'; geojson: CompleteBoundary; acres: number }
  | { kind: 'point'; point: FieldPoint }
  | { kind: 'polygon'; points: FieldPoint[]; acres: number }

export const validFieldPoint = (point: FieldPoint): boolean =>
  Number.isFinite(point.lat) && Number.isFinite(point.lon) &&
  point.lat >= -90 && point.lat <= 90 && point.lon >= -180 && point.lon <= 180

export const estimatePolygonAcres = (points: FieldPoint[]): number => {
  if (points.length < 3 || points.some((point) => !validFieldPoint(point))) {
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
  if (geometry.kind === 'geojson') return completeBoundaryIssue(geometry.geojson)
  if (geometry.kind === 'point') {
    return validFieldPoint(geometry.point) ? null : 'Field point coordinates are invalid.'
  }
  if (geometry.points.some((point) => !validFieldPoint(point))) {
    return 'Boundary coordinates are invalid.'
  }
  if (geometry.points.length < 3) {
    return 'Add at least three boundary vertices.'
  }
  if (polygonSelfIntersects(geometry.points)) {
    return 'Boundary edges cross. Edit the vertices before intersecting or saving.'
  }
  if (!Number.isFinite(geometry.acres) || geometry.acres <= 0 || estimatePolygonAcres(geometry.points) <= 0) {
    return 'Boundary vertices must enclose an area.'
  }
  return null
}

export const isUsableFieldGeometry = (geometry: FieldGeometry): boolean => fieldGeometryIssue(geometry) === null

/** Preserve complete imported boundaries. Server validation owns topology/CRS. */
export function completeBoundaryIssue(value: CompleteBoundary): string | null {
  const polygons = value.type === 'Polygon' ? [value.coordinates] : value.coordinates
  if (!Array.isArray(polygons) || !polygons.length) return 'Boundary polygons are missing.'
  let vertices = 0
  for (const polygon of polygons) {
    if (!Array.isArray(polygon) || !polygon.length) return 'Boundary rings are missing.'
    for (const ring of polygon) {
      if (!Array.isArray(ring) || ring.length < 4) return 'Each boundary ring needs at least four closed positions.'
      for (const point of ring) {
        if (!Array.isArray(point) || point.length !== 2 || !validFieldPoint({ lon: point[0], lat: point[1] })) return 'Boundary coordinates are invalid.'
        if (++vertices > 10000) return 'Boundary exceeds the 10,000-position limit.'
      }
      if (ring[0][0] !== ring[ring.length - 1][0] || ring[0][1] !== ring[ring.length - 1][1]) return 'Boundary rings must be closed.'
    }
  }
  return null
}

export function completeBoundaryGeometry(value: CompleteBoundary): FieldGeometry {
  const issue = completeBoundaryIssue(value)
  if (issue) throw new Error(issue)
  const polygons = value.type === 'Polygon' ? [value.coordinates] : value.coordinates
  const acres = polygons.reduce((total, polygon) => total + polygon.reduce((area, ring, index) =>
    area + (index === 0 ? 1 : -1) * estimatePolygonAcres(ring.slice(0, -1).map(([lon, lat]) => ({ lon, lat }))), 0), 0)
  return { kind: 'geojson', geojson: structuredClone(value), acres }
}

export function fieldGeometryGeoJson(geometry: FieldGeometry): { type: string; coordinates: unknown } | null {
  if (geometry.kind === 'none') return null
  if (geometry.kind === 'geojson') return geometry.geojson
  if (geometry.kind === 'point') return { type: 'Point', coordinates: [geometry.point.lon, geometry.point.lat] }
  const ring = geometry.points.map(({ lon, lat }) => [lon, lat])
  if (ring.length && (ring[0][0] !== ring[ring.length - 1][0] || ring[0][1] !== ring[ring.length - 1][1])) ring.push(ring[0])
  return { type: 'Polygon', coordinates: [ring] }
}

export function boundaryPoints(geometry: FieldGeometry): FieldPoint[] {
  if (geometry.kind === 'polygon') return geometry.points
  if (geometry.kind !== 'geojson') return []
  const polygons = geometry.geojson.type === 'Polygon' ? [geometry.geojson.coordinates] : geometry.geojson.coordinates
  return polygons.flatMap(polygon => polygon.flatMap(ring => ring.map(([lon, lat]) => ({ lon, lat }))))
}
