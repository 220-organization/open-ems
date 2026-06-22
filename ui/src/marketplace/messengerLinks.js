/** Same contact as B2B Telegram deep link (+380982204411), digits only for wa.me */
export const MESSENGER_PHONE = '380982204411';

/** Allowed distance-to-connection-point values (meters) on location lead form */
export const DISTANCE_METER_OPTIONS = [5, 10, 30, 50, 70, 100, 150, 200, 300];

/** Search radius around a map point for LOOKING submissions, km */
export const REGION_RADIUS_KM_OPTIONS = [1, 10, 25, 50, 75, 100];
export const REGION_RADIUS_KM_DEFAULT = 25;

export function formatRegionRadiusKm(radiusKm, t) {
  const n = Number(radiusKm);
  if (!Number.isFinite(n)) return '';
  return t('marketplaceLeadFormRegionRadiusValue', { value: n });
}

export function formatDistanceMeters(meters, t) {
  const n = Number(meters);
  if (!Number.isFinite(n)) return '';
  if (n === 5) return t('marketplaceLeadFormDistanceUpTo5');
  return `${n} m`;
}

export function buildGoogleMapsPointUrl(lat, lng) {
  return `https://www.google.com/maps?q=${Number(lat).toFixed(5)},${Number(lng).toFixed(5)}`;
}

export function formatLocationLine(index, label, lat, lng) {
  return `${index + 1}. ${label}\n${buildGoogleMapsPointUrl(lat, lng)}`;
}

export function buildTelegramUrl(message) {
  return `https://t.me/+${MESSENGER_PHONE}?text=${encodeURIComponent(message)}`;
}

export function buildWhatsAppUrl(message) {
  return `https://wa.me/${MESSENGER_PHONE}?text=${encodeURIComponent(message)}`;
}
