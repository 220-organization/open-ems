import { useEffect, useState } from 'react';
import { GOVMAP_HEATMAP_POINTS_URL } from './marketplaceHeatmapPoints';

export function useGovmapHeatmapPoints(enabled) {
  const [points, setPoints] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!enabled) {
      setPoints([]);
      return undefined;
    }

    let cancelled = false;
    setLoading(true);

    fetch(GOVMAP_HEATMAP_POINTS_URL)
      .then(res => {
        if (!res.ok) throw new Error('govmap fetch failed');
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
  }, [enabled]);

  return { points, loading };
}
