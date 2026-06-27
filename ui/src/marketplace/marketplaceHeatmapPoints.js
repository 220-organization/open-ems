/** Per-source contribution when aggregating marketplace demand heatmap cells. */
export const HEATMAP_WEIGHT_GOVMAP = 2;
export const HEATMAP_WEIGHT_EVUA = 8;

/** Show half of the heatmap visual strength (opacity + intensity). */
export const HEATMAP_CONTENT_VISIBLE_FRACTION = 0.5;
export const HEATMAP_LAYER_OPACITY = 0.65 * HEATMAP_CONTENT_VISIBLE_FRACTION;
export const HEATMAP_INTENSITY_SCALE = HEATMAP_CONTENT_VISIBLE_FRACTION;

export const GOVMAP_HEATMAP_POINTS_URL = `${process.env.PUBLIC_URL || ''}/static/govmap-heatmap-points.json`;

/** Group coords; finer grid when zoomed in so single sites stay visible. */
export const REGION_GROUP_PRECISION = 1;

export function precisionForZoom(zoom) {
  if (zoom >= 12) return 3;
  if (zoom >= 9) return 2;
  return REGION_GROUP_PRECISION;
}

export function buildHeatmapWeightedPoints(evuaStations, govmapPoints) {
  const points = [];
  (evuaStations || []).forEach(station => {
    const lat = Number(station?.lat);
    const lng = Number(station?.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
    points.push({ lat, lng, pointWeight: HEATMAP_WEIGHT_EVUA });
  });
  (govmapPoints || []).forEach(point => {
    const lat = Number(point?.lat);
    const lng = Number(point?.lng);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
    points.push({ lat, lng, pointWeight: HEATMAP_WEIGHT_GOVMAP });
  });
  return points;
}

/** Aggregate weighted coords into grid hotspots (cell score = sum of source weights). */
export function aggregateHeatmapPoints(points, groupPrecision = REGION_GROUP_PRECISION) {
  const groups = new Map();
  (points || []).forEach(point => {
    const lat = Number(point?.lat);
    const lng = Number(point?.lng);
    const pointWeight = Number(point?.pointWeight);
    if (!Number.isFinite(lat) || !Number.isFinite(lng) || !Number.isFinite(pointWeight) || pointWeight <= 0) {
      return;
    }
    const key = `${lat.toFixed(groupPrecision)}:${lng.toFixed(groupPrecision)}`;
    const existing = groups.get(key);
    if (existing) {
      existing.weightSum += pointWeight;
      existing.lat += lat * pointWeight;
      existing.lng += lng * pointWeight;
      existing.coordWeight += pointWeight;
    } else {
      groups.set(key, {
        weightSum: pointWeight,
        lat: lat * pointWeight,
        lng: lng * pointWeight,
        coordWeight: pointWeight,
      });
    }
  });

  const raw = Array.from(groups.values()).map(group => ({
    lat: group.lat / group.coordWeight,
    lng: group.lng / group.coordWeight,
    count: group.weightSum,
  }));
  if (!raw.length) return [];

  // Zoomed-in grid: keep every cell visible, including low single-source scores.
  if (groupPrecision >= 2) {
    const maxCount = Math.max(...raw.map(group => group.count));
    const logMax = Math.log1p(maxCount);
    return raw.map(group => ({
      lat: group.lat,
      lng: group.lng,
      weight: logMax > 0 ? Math.max(0.42, Math.log1p(group.count) / logMax) : 0.42,
    }));
  }

  const sortedCounts = raw.map(group => group.count).sort((a, b) => a - b);
  const topWarmStartIndex = Math.max(0, Math.ceil(sortedCounts.length * 0.5) - 1);
  const topWarmThreshold = sortedCounts[topWarmStartIndex] ?? sortedCounts[sortedCounts.length - 1];
  const maxCount = sortedCounts[sortedCounts.length - 1];
  const logTopWarm = Math.log1p(topWarmThreshold);
  const logMax = Math.log1p(maxCount);

  return raw.map(group => {
    const logCount = Math.log1p(group.count);
    let weight;

    if (logCount <= logTopWarm || logMax <= logTopWarm) {
      weight = logTopWarm > 0 ? (logCount / logTopWarm) * 0.55 : 0.2;
    } else {
      const topSpan = logMax - logTopWarm;
      weight = topSpan > 0 ? 0.55 + ((logCount - logTopWarm) / topSpan) * 0.45 : 1;
    }

    return { lat: group.lat, lng: group.lng, weight };
  });
}
