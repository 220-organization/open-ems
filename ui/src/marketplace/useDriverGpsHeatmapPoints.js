import { useEffect, useState } from 'react';

const HEATMAP_POINTS_URL = '/api/ev-driver-tracker/heatmap-points';

export function useDriverGpsHeatmapPoints(enabled, days = 90) {
  const [points, setPoints] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!enabled) {
      setPoints([]);
      return undefined;
    }

    let cancelled = false;
    setLoading(true);

    fetch(`${HEATMAP_POINTS_URL}?days=${days}`)
      .then(res => {
        if (!res.ok) throw new Error('driver gps heatmap fetch failed');
        return res.json();
      })
      .then(data => {
        if (cancelled) return;
        const rows = Array.isArray(data) ? data : data?.points;
        setPoints(Array.isArray(rows) ? rows : []);
      })
      .catch(() => {
        if (!cancelled) setPoints([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [enabled, days]);

  return { points, loading };
}
