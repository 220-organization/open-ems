import { useCallback, useState } from 'react';
import { notifyOpenEmsSearchChange } from '../sharePageQr';

export const MARKETPLACE_LOCATION_QUERY = 'location';

export function buildMarketplaceShareUrl() {
  if (typeof window === 'undefined') return '/marketplace';
  return `${window.location.origin}/marketplace`;
}

/** Absolute marketplace URL that opens one published location card. */
export function buildMarketplaceLocationShareUrl(locationId, { origin, lang } = {}) {
  const base =
    origin ||
    (typeof window !== 'undefined' ? window.location.origin : 'http://localhost');
  const url = new URL('/marketplace', base);
  const resolvedLang =
    lang !== undefined
      ? lang
      : typeof window !== 'undefined'
        ? new URLSearchParams(window.location.search).get('lang')
        : '';
  if (resolvedLang) url.searchParams.set('lang', resolvedLang);
  if (locationId) url.searchParams.set(MARKETPLACE_LOCATION_QUERY, String(locationId));
  return url.toString();
}

export function readSharedMarketplaceLocationId() {
  if (typeof window === 'undefined') return '';
  try {
    return new URLSearchParams(window.location.search).get(MARKETPLACE_LOCATION_QUERY) || '';
  } catch {
    return '';
  }
}

/** Keep ?location= in the address bar so the header share button matches the open card. */
export function writeSharedMarketplaceLocationId(locationId) {
  if (typeof window === 'undefined') return;
  try {
    const url = new URL(window.location.href);
    const next = locationId ? String(locationId) : '';
    const current = url.searchParams.get(MARKETPLACE_LOCATION_QUERY) || '';
    if (current === next) return;
    if (next) url.searchParams.set(MARKETPLACE_LOCATION_QUERY, next);
    else url.searchParams.delete(MARKETPLACE_LOCATION_QUERY);
    window.history.replaceState({}, '', url);
    notifyOpenEmsSearchChange();
  } catch {
    /* ignore */
  }
}

export default function ShareButton({ t }) {
  const [copied, setCopied] = useState(false);

  const copyLink = useCallback(async () => {
    const url = buildMarketplaceShareUrl();
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }, []);

  return (
    <div className="marketplace-share-row">
      <button type="button" className="marketplace-share-btn" onClick={() => void copyLink()}>
        {copied ? t('marketplaceShareCopied') : t('marketplaceShareBtn')}
      </button>
    </div>
  );
}
