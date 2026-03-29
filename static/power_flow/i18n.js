/**
 * Lightweight i18n for the Power flow static UI.
 * Locales: en, uk, pl, cs, nl, bg, fr, es. Aliases: cz→cs, ua→uk.
 */

const STORAGE_KEY = 'pf-lang';

const SUPPORTED = ['en', 'uk', 'pl', 'cs', 'nl', 'bg', 'fr', 'es'];

const ALIASES = {
  cz: 'cs',
  ua: 'uk',
};

const BCP47 = {
  en: 'en-GB',
  uk: 'uk-UA',
  pl: 'pl-PL',
  cs: 'cs-CZ',
  nl: 'nl-NL',
  bg: 'bg-BG',
  fr: 'fr-FR',
  es: 'es-ES',
};

/** Native / familiar names for the language selector */
export const LOCALE_NAMES = {
  en: 'English',
  uk: 'Українська',
  pl: 'Polski',
  cs: 'Čeština',
  nl: 'Nederlands',
  bg: 'Български',
  fr: 'Français',
  es: 'Español',
};

let current = 'uk';
let messages = {};
let onLocaleChangeCb = null;

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
  const nav = normalizeLang(navigator.language || navigator.userLanguage);
  if (nav) return nav;
  return 'uk';
}

function interpolate(str, vars) {
  if (!vars) return str;
  return str.replace(/\{\{(\w+)\}\}/g, (_, k) => (vars[k] != null ? String(vars[k]) : ''));
}

export function t(key, vars) {
  const raw = messages[key];
  const str = raw != null ? raw : key;
  return interpolate(str, vars);
}

export function getLocale() {
  return current;
}

export function getBcp47Locale() {
  return BCP47[current] || 'en-GB';
}

async function loadMessages(lang) {
  const base = new URL('./locales/', import.meta.url);
  const url = new URL(`${lang}.json`, base);
  const r = await fetch(url.href);
  if (!r.ok) throw new Error(`Failed to load locale ${lang}: ${r.status}`);
  return r.json();
}

function applyStaticDom() {
  document.title = t('pageTitle');
  document.documentElement.lang = current === 'uk' ? 'uk' : current;

  const stationLabel = document.getElementById('pf-station-label');
  if (stationLabel) stationLabel.textContent = t('stationLabel');

  const stationInput = document.getElementById('pf-station');
  if (stationInput) stationInput.placeholder = t('stationPlaceholder');

  const graph = document.getElementById('pf-graph');
  if (graph) graph.setAttribute('aria-label', t('graphAriaLabel'));

  const aside = document.querySelector('.pf-ukraine-qr');
  if (aside) aside.setAttribute('aria-label', t('qrAsideAria'));

  const img = document.querySelector('.pf-ukraine-qr-img');
  if (img) img.setAttribute('alt', t('qrImageAlt'));

  const cap = document.querySelector('.pf-ukraine-qr-caption');
  if (cap) cap.textContent = t('qrCaption');

  const langSelect = document.getElementById('pf-lang');
  if (langSelect) {
    langSelect.setAttribute('aria-label', t('langSelectAria'));
    langSelect.value = current;
  }

  const invLabel = document.getElementById('pf-inverter-label');
  if (invLabel) invLabel.textContent = t('inverterLabel');

  const invSelect = document.getElementById('pf-inverter');
  if (invSelect) invSelect.setAttribute('aria-label', t('inverterSelectAria'));
}

function wireLangSelect() {
  const langSelect = document.getElementById('pf-lang');
  if (!langSelect) return;
  langSelect.innerHTML = SUPPORTED.map(
    (code) => `<option value="${code}">${LOCALE_NAMES[code] || code}</option>`,
  ).join('');
  langSelect.value = current;
  langSelect.addEventListener('change', async () => {
    const next = normalizeLang(langSelect.value);
    if (!next || next === current) return;
    await setLocale(next);
    try {
      const u = new URL(window.location.href);
      u.searchParams.set('lang', next);
      window.history.replaceState({}, '', u);
    } catch {
      /* ignore */
    }
  });
}

export async function setLocale(lang) {
  const next = normalizeLang(lang);
  if (!next) return;
  current = next;
  try {
    localStorage.setItem(STORAGE_KEY, current);
  } catch {
    /* ignore */
  }
  messages = await loadMessages(current);
  applyStaticDom();
  if (typeof onLocaleChangeCb === 'function') onLocaleChangeCb();
}

/**
 * @param {{ onLocaleChange?: () => void }} [opts]
 */
export async function initI18n(opts = {}) {
  onLocaleChangeCb = opts.onLocaleChange || null;
  current = resolveInitialLang();
  wireLangSelect();
  try {
    messages = await loadMessages(current);
  } catch {
    current = 'en';
    messages = await loadMessages('en');
  }
  applyStaticDom();
}

export { SUPPORTED as SUPPORTED_LOCALES };
