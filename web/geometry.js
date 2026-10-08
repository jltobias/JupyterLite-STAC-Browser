/** Deliberately bounded, planar validation for one WGS84 polygon without holes. */
export function rectangleGeometry([w, s, e, n]) {
  return {type: 'Polygon', coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]]};
}

export function geometryBBox(geometry) {
  const ring = geometry.coordinates[0];
  return [Math.min(...ring.map(p => p[0])), Math.min(...ring.map(p => p[1])), Math.max(...ring.map(p => p[0])), Math.max(...ring.map(p => p[1]))];
}

export function polygonValue(value) {
  const ring = value?.coordinates?.[0];
  const fail = message => { throw new Error(message); };
  if (value?.type !== 'Polygon' || !Array.isArray(value.coordinates) || value.coordinates.length !== 1 || !Array.isArray(ring) || ring.length < 4 || ring.length > 501) {
    fail('Use one Polygon with 3–500 vertices and one closed ring; holes and MultiPolygons are not supported.');
  }
  if (!ring.every(p => Array.isArray(p) && p.length === 2 && p.every(Number.isFinite) && p[0] >= -180 && p[0] <= 180 && p[1] >= -90 && p[1] <= 90)) {
    fail('Polygon coordinates must be longitude/latitude within ±180°/±90°. Split date-line areas into separate searches.');
  }
  const same = (a, b) => a[0] === b[0] && a[1] === b[1];
  if (!same(ring[0], ring.at(-1))) fail('Polygon ring must be closed.');
  const cross = (a, b, c) => (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
  const onSegment = (a, b, p) => cross(a, b, p) === 0 && p[0] >= Math.min(a[0], b[0]) && p[0] <= Math.max(a[0], b[0]) && p[1] >= Math.min(a[1], b[1]) && p[1] <= Math.max(a[1], b[1]);
  const intersects = (a, b, c, d) => {
    const abC = cross(a, b, c), abD = cross(a, b, d), cdA = cross(c, d, a), cdB = cross(c, d, b);
    return (abC * abD < 0 && cdA * cdB < 0) || onSegment(a, b, c) || onSegment(a, b, d) || onSegment(c, d, a) || onSegment(c, d, b);
  };
  const count = ring.length - 1;
  let area = 0;
  for (let i = 0; i < count; i++) {
    const a = ring[i], b = ring[i + 1], c = ring[(i + 2) % count];
    if (same(a, b)) fail('Polygon has duplicate neighboring vertices.');
    if (Math.abs(a[0] - b[0]) > 180) fail('Polygon crosses the antimeridian. Split date-line areas into separate searches.');
    if (cross(a, b, c) === 0 && ((a[0] - b[0]) * (c[0] - b[0]) + (a[1] - b[1]) * (c[1] - b[1])) > 0) fail('Polygon edges overlap. Move or remove the overlapping vertex.');
    // Translate to the first vertex to avoid cancellation for small areas far from zero.
    area += (a[0] - ring[0][0]) * (b[1] - ring[0][1]) - (b[0] - ring[0][0]) * (a[1] - ring[0][1]);
    for (let j = i + 2; j < count; j++) {
      if (i === 0 && j === count - 1) continue;
      if (intersects(a, b, ring[j], ring[j + 1])) fail('Polygon edges cross or touch. Move or remove vertices to make a simple area.');
    }
  }
  if (area === 0) fail('Polygon must enclose a nonzero area.');
  return {type: 'Polygon', coordinates: [ring.map(p => [...p])]};
}
