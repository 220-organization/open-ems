import { clarity } from 'react-microsoft-clarity';

const clarityProjectId = (process.env.REACT_APP_CLARITY_PROJECT_ID || '').trim();

let analyticsStarted = false;

export function initAnalytics() {
  if (process.env.NODE_ENV !== 'production') return;
  if (!clarityProjectId || analyticsStarted) return;

  clarity.init(clarityProjectId);
  analyticsStarted = true;
}

/** Tag SPA route changes for Clarity filters (pathname-based router, no full reload). */
export function trackPageView(page, pathname) {
  if (process.env.NODE_ENV !== 'production') return;
  if (!analyticsStarted || !clarity.hasStarted()) return;

  clarity.setTag('page', page);
  if (pathname) {
    clarity.setTag('path', pathname);
  }
}
