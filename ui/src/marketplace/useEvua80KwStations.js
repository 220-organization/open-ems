import { useEffect, useState } from 'react';

const B2B_API_BASE = (process.env.REACT_APP_B2B_API_URL || 'https://220-km.com:8080').replace(/\/$/, '');

export function useEvua80KwStations(enabled) {
  const [stations, setStations] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!enabled) {
      setStations([]);
      return undefined;
    }

    let cancelled = false;
    setLoading(true);

    fetch(`${B2B_API_BASE}/api/roaming/evua/stations`)
      .then(res => {
        if (!res.ok) throw new Error('evua fetch failed');
        return res.json();
      })
      .then(data => {
        if (!cancelled) setStations(Array.isArray(data) ? data : data?.items || []);
      })
      .catch(() => {
        if (!cancelled) setStations([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [enabled]);

  return { stations, loading };
}
