import { useEffect, useState } from 'react';

/** True when viewport width is at least minWidthPx (matches CSS min-width media query). */
export function useMinWidth(minWidthPx) {
  const [matches, setMatches] = useState(() => {
    if (typeof window === 'undefined') return false;
    return window.matchMedia(`(min-width: ${minWidthPx}px)`).matches;
  });

  useEffect(() => {
    const mql = window.matchMedia(`(min-width: ${minWidthPx}px)`);
    const handler = () => setMatches(mql.matches);
    mql.addEventListener('change', handler);
    handler();
    return () => mql.removeEventListener('change', handler);
  }, [minWidthPx]);

  return matches;
}
