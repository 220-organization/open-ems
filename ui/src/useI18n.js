import { useCallback, useMemo, useState } from 'react';
import bg from './locales/bg.json';
import cs from './locales/cs.json';
import de from './locales/de.json';
import en from './locales/en.json';
import es from './locales/es.json';
import fr from './locales/fr.json';
import nl from './locales/nl.json';
import pl from './locales/pl.json';
import uk from './locales/uk.json';

const BUNDLES = { en, uk, pl, cs, nl, bg, fr, es, de };

const SUPPORTED = ['en', 'uk', 'pl', 'cs', 'nl', 'bg', 'fr', 'es', 'de'];

const ALIASES = { cz: 'cs', ua: 'uk' };

const BCP47 = {
  en: 'en-GB',
  uk: 'uk-UA',
  pl: 'pl-PL',
  cs: 'cs-CZ',
  nl: 'nl-NL',
  bg: 'bg-BG',
  fr: 'fr-FR',
  es: 'es-ES',
  de: 'de-DE',
};

export const LOCALE_NAMES = {
  en: 'English',
  uk: 'Українська',
  pl: 'Polski',
  cs: 'Čeština',
  nl: 'Nederlands',
  bg: 'Български',
  fr: 'Français',
  es: 'Español',
  de: 'Deutsch',
};

const STORAGE_KEY = 'pf-lang';

function normalizeLang(raw) {
  if (!raw || typeof raw !== 'string') return null;
  const key = raw.trim().toLowerCase().replace('_', '-');
  const two = key.split('-')[0];
  if (ALIASES[key]) return ALIASES[key];
  if (ALIASES[two]) return ALIASES[two];
  if (SUPPORTED.includes(key)) return key;
  if (SUPPORTED.includes(two)) return two;
  return null;
}

function resolveInitialLang() {
  try {
    const params = new URLSearchParams(window.location.search);
    const fromUrl = normalizeLang(params.get('lang') || params.get('locale'));
    if (fromUrl) return fromUrl;
  } catch {
    /* ignore */
  }
  try {
    const stored = normalizeLang(localStorage.getItem(STORAGE_KEY));
    if (stored) return stored;
  } catch {
    /* ignore */
  }
  // Default to Ukrainian on first open; URL ?lang= and localStorage still override.
  return 'uk';
}

function interpolate(str, vars) {
  if (!vars) return str;
  return str.replace(/\{\{(\w+)\}\}/g, (_, k) => (vars[k] != null ? String(vars[k]) : ''));
}

export function useI18n() {
  const [locale, setLocaleState] = useState(resolveInitialLang);

  const bundle = BUNDLES[locale] || BUNDLES.en;

  const t = useCallback(
    (key, vars) => {
      const raw = bundle[key];
      const str = raw != null ? raw : key;
      return interpolate(str, vars);
    },
    [bundle],
  );

  const getBcp47Locale = useCallback(() => BCP47[locale] || 'en-GB', [locale]);

  const setLocale = useCallback((nextRaw) => {
    const next = normalizeLang(nextRaw);
    if (!next) return;
    setLocaleState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* ignore */
    }
    try {
      const u = new URL(window.location.href);
      u.searchParams.set('lang', next);
      window.history.replaceState({}, '', u);
    } catch {
      /* ignore */
    }
  }, []);

  const onLangSelectChange = useCallback(
    (e) => {
      setLocale(e.target.value);
    },
    [setLocale],
  );

  return useMemo(
    () => ({
      locale,
      setLocale,
      t,
      getBcp47Locale,
      SUPPORTED,
      LOCALE_NAMES,
      onLangSelectChange,
    }),
    [locale, setLocale, t, getBcp47Locale, onLangSelectChange],
  );
}
