/**
 * Google Analytics (gtag) + Microsoft Clarity when env vars are set at build time.
 * Set REACT_APP_GA_MEASUREMENT_ID (GA4 G-… or legacy UA-…) and REACT_APP_CLARITY_PROJECT_ID.
 */
import { clarity } from 'react-microsoft-clarity';

let initialized = false;

export function initAnalytics() {
  if (initialized || typeof window === 'undefined') return;
  initialized = true;

  const clarityId = process.env.REACT_APP_CLARITY_PROJECT_ID?.trim();
  if (clarityId) {
    try {
      clarity.init(clarityId);
    } catch (e) {
      console.warn('[open-ems] Clarity init failed', e);
    }
  }

  const gaId = process.env.REACT_APP_GA_MEASUREMENT_ID?.trim();
  if (!gaId) return;

  const script = document.createElement('script');
  script.async = true;
  script.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(gaId)}`;
  document.head.appendChild(script);

  window.dataLayer = window.dataLayer || [];
  window.gtag = function gtag() {
    window.dataLayer.push(arguments);
  };
  window.gtag('js', new Date());
  window.gtag('config', gaId, {
    anonymize_ip: true,
    send_page_view: true,
  });
}

/**
 * Optional SPA page views (e.g. after client-side path changes).
 */
export function trackPageView(path) {
  const gaId = process.env.REACT_APP_GA_MEASUREMENT_ID?.trim();
  if (!gaId || typeof window === 'undefined' || typeof window.gtag !== 'function') return;
  window.gtag('event', 'page_view', {
    page_path: path || window.location.pathname,
    page_title: document.title,
    send_to: gaId,
  });
}
