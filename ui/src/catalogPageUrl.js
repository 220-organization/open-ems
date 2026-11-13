/**
 * Catalog URL for a buy request: the address the user is on, including
 * the filter query already in the location bar (brand, power, and the rest).
 * `extra` overlays keys such as the chosen sku without dropping those filters.
 */
export function catalogPageUrlFromLocation(extra = {}) {
  if (typeof window === "undefined") return "";
  const u = new URL(window.location.href);
  Object.entries(extra).forEach(([key, val]) => {
    const text = val == null ? "" : String(val).trim();
    if (text) u.searchParams.set(key, text);
  });
  u.hash = "";
  return `${u.origin}${u.pathname}${u.search}`;
}
