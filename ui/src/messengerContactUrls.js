/** Same B2B contact as 220-km.com/b2b — digits only for wa.me */
export const B2B_MESSENGER_PHONE = '380982204411';

export function buildB2bTelegramUrl(message) {
  return `https://t.me/+${B2B_MESSENGER_PHONE}?text=${encodeURIComponent(message)}`;
}

export function buildB2bWhatsAppUrl(message) {
  return `https://wa.me/${B2B_MESSENGER_PHONE}?text=${encodeURIComponent(message)}`;
}

/** Share an arbitrary page URL via Telegram (opens share sheet / choose chat). */
export function buildTelegramShareUrl(pageUrl, text = '') {
  const u = new URL('https://t.me/share/url');
  u.searchParams.set('url', pageUrl);
  if (text) u.searchParams.set('text', text);
  return u.toString();
}

/** Share an arbitrary page URL via WhatsApp. */
export function buildWhatsAppShareUrl(pageUrl, text = '') {
  const body = text ? `${text}\n${pageUrl}` : pageUrl;
  return `https://wa.me/?text=${encodeURIComponent(body)}`;
}
