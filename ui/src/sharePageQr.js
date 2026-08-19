import { useEffect, useState } from 'react';

/** Fired after SPA replaceState that changes search (hub logo pin, etc.). */
export const OPEN_EMS_SEARCH_CHANGE_EVENT = 'open-ems:search';

export function notifyOpenEmsSearchChange() {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new Event(OPEN_EMS_SEARCH_CHANGE_EVENT));
}

/** Live share URL: updates on popstate and `open-ems:search`. */
export function usePageShareUrl() {
  const [url, setUrl] = useState(() => pageShareUrlFromWindow());
  useEffect(() => {
    const sync = () => setUrl(pageShareUrlFromWindow());
    window.addEventListener('popstate', sync);
    window.addEventListener(OPEN_EMS_SEARCH_CHANGE_EVENT, sync);
    return () => {
      window.removeEventListener('popstate', sync);
      window.removeEventListener(OPEN_EMS_SEARCH_CHANGE_EVENT, sync);
    };
  }, []);
  return url;
}

/** Current page URL without hash — safe for sharing and QR encoding. */
export function pageShareUrlFromWindow(options = {}) {
  if (typeof window === 'undefined') return '';
  const { stripParams = ['kiosk'] } = options;
  try {
    const u = new URL(window.location.href.split('#')[0]);
    stripParams.forEach(key => u.searchParams.delete(key));
    return u.toString();
  } catch {
    return '';
  }
}

/** Copy share URL to clipboard when available. */
export async function copySharePageUrl(url) {
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(url);
      return true;
    }
  } catch {
    /* ignore */
  }
  return false;
}

/** URL + clipboard status for SharePageModal (header share btn and graph QR). */
export async function buildSharePageModalPayload() {
  const url = pageShareUrlFromWindow();
  if (!url) return null;
  const copied = await copySharePageUrl(url);
  return { url, copied, copyFailed: !copied };
}
