/** Monobank redirectUrl target after marketplace payment (Open EMS /marketplace). */
export const MARKETPLACE_PAY_REDIRECT_BASE = (
  process.env.REACT_APP_MARKETPLACE_PAY_REDIRECT_URL || 'https://220-km.com:9220/marketplace'
)
  .trim()
  .replace(/\/$/, '');

export function buildMarketplacePayRedirectBase() {
  if (typeof window === 'undefined') return MARKETPLACE_PAY_REDIRECT_BASE;
  const { hostname } = window.location;
  if (hostname === 'localhost' || hostname === '127.0.0.1') {
    if (process.env.REACT_APP_MARKETPLACE_PAY_REDIRECT_URL) {
      return MARKETPLACE_PAY_REDIRECT_BASE;
    }
    return `${window.location.origin}/marketplace`;
  }
  return MARKETPLACE_PAY_REDIRECT_BASE;
}
