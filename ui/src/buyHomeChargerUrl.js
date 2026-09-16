/** Shareable query state for `/buy-home-charger`. */

export const HOME_CHARGER_DEFAULT_SORT = "price-asc";
export const HOME_CHARGER_KIND_IDS = ["charger", "accessory"];
export const HOME_CHARGER_POWER_IDS = ["upto4", "7to8", "11", "22plus"];
export const HOME_CHARGER_PHASE_IDS = ["1", "3"];
export const HOME_CHARGER_SORT_IDS = ["price-asc", "price-desc", "power-desc"];

export function parseHomeChargerCatalogSearch(search) {
  const raw = String(search || "");
  const u = new URLSearchParams(raw.startsWith("?") ? raw.slice(1) : raw);
  const out = {};
  const kind = (u.get("kind") || "").trim();
  if (HOME_CHARGER_KIND_IDS.includes(kind)) out.kind = kind;
  const power = (u.get("power") || "").trim();
  if (HOME_CHARGER_POWER_IDS.includes(power)) out.power = power;
  const connector = (u.get("connector") || "").trim();
  if (connector) out.connector = connector;
  const phases = (u.get("phases") || "").trim();
  if (HOME_CHARGER_PHASE_IDS.includes(phases)) out.phases = phases;
  const brand = (u.get("brand") || "").trim();
  if (brand) out.brand = brand;
  const sku = (u.get("sku") || "").trim();
  if (sku) out.sku = sku;
  const sort = (u.get("sort") || "").trim();
  if (HOME_CHARGER_SORT_IDS.includes(sort)) out.sort = sort;
  return out;
}

export function applyHomeChargerCatalogSearch(params, state) {
  const u =
    params instanceof URLSearchParams
      ? params
      : new URLSearchParams(params || "");
  const setOrDel = (key, val) => {
    if (val) u.set(key, val);
    else u.delete(key);
  };
  setOrDel("kind", state.kind);
  setOrDel("power", state.power);
  setOrDel("connector", state.connector);
  setOrDel("phases", state.phases);
  setOrDel("brand", state.brand);
  setOrDel("sku", state.sku);
  if (state.sort && state.sort !== HOME_CHARGER_DEFAULT_SORT)
    u.set("sort", state.sort);
  else u.delete("sort");
  return u;
}
