/** Same B2B contact as 220-km.com/b2b — digits only for wa.me */
export const B2B_MESSENGER_PHONE = '380982204411';

export function buildB2bTelegramUrl(message) {
  return `https://t.me/+${B2B_MESSENGER_PHONE}?text=${encodeURIComponent(message)}`;
}

export function buildB2bWhatsAppUrl(message) {
  return `https://wa.me/${B2B_MESSENGER_PHONE}?text=${encodeURIComponent(message)}`;
}
