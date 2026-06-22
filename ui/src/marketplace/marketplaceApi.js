const ADMIN_PORTAL_API_URL =
  process.env.REACT_APP_ADMIN_PORTAL_API_URL || 'https://220-km.com:8090';

function apiBase() {
  return (ADMIN_PORTAL_API_URL || '').replace(/\/$/, '');
}

export function isMarketplaceApiConfigured() {
  return Boolean(apiBase());
}

export function resolveMarketplaceAssetUrl(pathOrUrl) {
  if (!pathOrUrl) return pathOrUrl;
  if (/^https?:\/\//i.test(pathOrUrl)) return pathOrUrl;
  const base = apiBase();
  if (!base) return pathOrUrl;
  return `${base}${pathOrUrl.startsWith('/') ? pathOrUrl : `/${pathOrUrl}`}`;
}

export async function uploadMarketplaceFile(file) {
  const base = apiBase();
  if (!base || !file) return null;

  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch(`${base}/marketplace/uploads`, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    throw new Error(`Upload failed (${response.status})`);
  }

  const data = await response.json();
  return resolveMarketplaceAssetUrl(data.url);
}

export async function submitMarketplaceLocation(payload) {
  const base = apiBase();
  if (!base) return null;

  const response = await fetch(`${base}/marketplace/locations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error(`Submit failed (${response.status})`);
  }

  return response.json();
}

export async function fetchMarketplaceLocations(requestType) {
  const base = apiBase();
  if (!base) return [];

  const query = requestType ? `?request_type=${encodeURIComponent(requestType)}` : '';
  const response = await fetch(`${base}/marketplace/locations${query}`);

  if (!response.ok) {
    throw new Error(`Fetch failed (${response.status})`);
  }

  const data = await response.json();
  return data.items || [];
}

export async function requestMarketplaceLocationInfo(locationId) {
  const base = apiBase();
  if (!base || !locationId) return null;

  const response = await fetch(`${base}/marketplace/locations/${locationId}/request-info`, {
    method: 'POST',
  });

  if (!response.ok) {
    throw new Error(`Request info failed (${response.status})`);
  }

  return response.json();
}

export async function createMarketplaceInfoPayment(locationId, { redirectBaseUrl, clientUiId } = {}) {
  const base = apiBase();
  if (!base || !locationId) return null;

  const response = await fetch(`${base}/marketplace/locations/${locationId}/pay`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      redirect_base_url: redirectBaseUrl,
      client_ui_id: clientUiId || null,
    }),
  });

  if (!response.ok) {
    throw new Error(`Payment init failed (${response.status})`);
  }

  return response.json();
}

export async function createMarketplaceTestPayment(locationId, { clientUiId } = {}) {
  const base = apiBase();
  if (!base || !locationId) return null;

  const response = await fetch(`${base}/marketplace/locations/${locationId}/pay-test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      client_ui_id: clientUiId || null,
    }),
  });

  if (!response.ok) {
    throw new Error(`Test payment failed (${response.status})`);
  }

  return response.json();
}

export async function createHeatmapZoomPayment({ redirectBaseUrl, clientUiId } = {}) {
  const base = apiBase();
  if (!base) return null;

  const response = await fetch(`${base}/marketplace/heatmap/pay`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      redirect_base_url: redirectBaseUrl,
      client_ui_id: clientUiId || null,
    }),
  });

  if (!response.ok) {
    throw new Error(`Heatmap payment init failed (${response.status})`);
  }

  return response.json();
}

export async function createHeatmapZoomTestPayment({ clientUiId } = {}) {
  const base = apiBase();
  if (!base) return null;

  const response = await fetch(`${base}/marketplace/heatmap/pay-test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      client_ui_id: clientUiId || null,
    }),
  });

  if (!response.ok) {
    throw new Error(`Heatmap test payment failed (${response.status})`);
  }

  return response.json();
}

function isLocalHostname(hostname) {
  return hostname === 'localhost' || hostname === '127.0.0.1';
}

export function isMarketplaceLocalTestPaymentEnabled() {
  if (process.env.NODE_ENV === 'production' && process.env.REACT_APP_ENV !== 'local') return false;
  if (typeof window !== 'undefined' && isLocalHostname(window.location.hostname)) {
    return true;
  }
  const base = apiBase();
  if (!base) return false;
  try {
    const { hostname } = new URL(base);
    return isLocalHostname(hostname);
  } catch {
    return false;
  }
}

export async function fetchMarketplacePaymentStatus(paymentId) {
  const base = apiBase();
  if (!base || !paymentId) return null;

  const response = await fetch(`${base}/marketplace/payments/${paymentId}`);

  if (!response.ok) {
    throw new Error(`Payment status failed (${response.status})`);
  }

  return response.json();
}

const UNLOCK_STORAGE_KEY = 'marketplaceUnlockedPayments';

export function getStoredMarketplacePaymentId(locationId) {
  if (!locationId || typeof window === 'undefined') return null;
  try {
    const map = JSON.parse(window.localStorage.getItem(UNLOCK_STORAGE_KEY) || '{}');
    return map[String(locationId)] || null;
  } catch {
    return null;
  }
}

export function storeMarketplaceUnlockedPayment(locationId, paymentId) {
  if (!locationId || !paymentId || typeof window === 'undefined') return;
  try {
    const map = JSON.parse(window.localStorage.getItem(UNLOCK_STORAGE_KEY) || '{}');
    map[String(locationId)] = String(paymentId);
    window.localStorage.setItem(UNLOCK_STORAGE_KEY, JSON.stringify(map));
  } catch {
    /* ignore quota / private mode */
  }
}
