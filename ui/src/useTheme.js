import { useEffect, useState } from 'react';

const STORAGE_KEY = 'pf-theme';

// Daylight window in 24h local time. Used when no manual preference is active:
// inside the window the auto theme is light, outside it is dark.
// 06:00–20:00 covers the daylight portion of the day across the year for
// Ukrainian latitudes; tweak if a different policy is needed.
const DAYLIGHT_START_HOUR = 6;
const DAYLIGHT_END_HOUR = 20;

// How often (ms) to re-check time-of-day so the auto theme can flip without a
// page reload and so a manual choice from yesterday is dropped after midnight.
const TICK_INTERVAL_MS = 60 * 1000;

/** YYYY-MM-DD in local time, used to expire manual choices at midnight. */
function todayKey() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function isDaylightNow() {
  const h = new Date().getHours();
  return h >= DAYLIGHT_START_HOUR && h < DAYLIGHT_END_HOUR;
}

/**
 * Read the user-saved preference, but only honour it if it was stored today.
 * After local midnight the manual choice expires and we fall back to 'system'
 * (= auto by daylight).
 */
function readPreference() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return 'system';
    // Backwards compat: an older build stored the value as a plain string.
    if (raw === 'light' || raw === 'dark') {
      // No stored date → treat as expired so the new behaviour kicks in.
      localStorage.removeItem(STORAGE_KEY);
      return 'system';
    }
    const parsed = JSON.parse(raw);
    if (
      parsed &&
      parsed.date === todayKey() &&
      (parsed.theme === 'light' || parsed.theme === 'dark')
    ) {
      return parsed.theme;
    }
    localStorage.removeItem(STORAGE_KEY);
    return 'system';
  } catch {
    return 'system';
  }
}

function savePreference(value) {
  try {
    if (value === 'system') {
      localStorage.removeItem(STORAGE_KEY);
    } else {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ theme: value, date: todayKey() })
      );
    }
  } catch {}
}

/**
 * Theme management hook.
 *
 * Defaults:
 *  - 'system' = auto-resolve by local time-of-day (light during DAYLIGHT_START_HOUR..DAYLIGHT_END_HOUR, dark otherwise).
 *  - Manual 'light'/'dark' choices persist in localStorage but expire at local midnight.
 *
 * Returns:
 *  - theme: 'system' | 'light' | 'dark'  — explicit user preference
 *  - isDark: boolean — effective resolved theme
 *  - cycleTheme: () => void — cycles system → light → dark → system
 */
export function useTheme() {
  const [theme, setTheme] = useState(readPreference);
  const [autoIsDark, setAutoIsDark] = useState(() => !isDaylightNow());

  // Re-evaluate daylight + check whether yesterday's manual choice has expired.
  // Runs roughly every minute so we cross the daylight boundary and the
  // midnight boundary without a manual reload.
  useEffect(() => {
    const tick = () => {
      setAutoIsDark(!isDaylightNow());
      // If the stored manual choice is no longer valid (different day), drop it.
      const fresh = readPreference();
      setTheme(prev => (prev !== 'system' && fresh === 'system' ? 'system' : prev));
    };
    const id = window.setInterval(tick, TICK_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, []);

  const isDark = theme === 'dark' || (theme === 'system' && autoIsDark);

  // Always write data-theme so CSS doesn't fall back to OS @media query.
  // This makes 'system' mean "auto by daylight", not "auto by OS preference".
  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute('data-theme', isDark ? 'dark' : 'light');
    savePreference(theme);
  }, [theme, isDark]);

  function cycleTheme() {
    setTheme(prev => {
      if (prev === 'system') return isDark ? 'light' : 'dark';
      if (prev === 'light') return 'dark';
      return 'system';
    });
  }

  return { theme, setTheme, isDark, cycleTheme };
}
