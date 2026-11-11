import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BUSINESS_TYPES,
  CUSTOM_PRESET_ID,
  DISCOUNT_UNITS,
  INVERTERS,
  BATTERY_MODELS,
  PRESETS,
  SIGENERGY_PRESETS,
  SIGEN_INVERTERS,
  SIGEN_BATTERIES,
  allowedKwhOptions,
  buildCustomBom,
  buildSigenBom,
  sigenCompatibleBatteryFamily,
  sigenKwhOptions,
  computeBiomSavings,
  kwhRangeLabel,
  unitPriceUsd,
  hasNoArrivalDates,
  isEtuVendor,
  presetSegment,
  presetBrand,
} from "./orderBess/presets";
import { downloadOrderBessOfferPng } from "./orderBess/offerPdf";
import SharePageModal from "./SharePageModal";
import { buildSharePageModalPayload } from "./sharePageQr";
import "./order-bess.css";

const VALID_BIZ = new Set(BUSINESS_TYPES.map((b) => b.id));
const ALL_PRESETS = [...PRESETS, ...SIGENERGY_PRESETS];
const VALID_PRESETS = new Set([
  ...ALL_PRESETS.map((p) => p.id),
  CUSTOM_PRESET_ID,
]);

function apiUrl(path) {
  const base = (process.env.REACT_APP_API_BASE_URL || "").replace(/\/$/, "");
  return base ? `${base}${path}` : path;
}

function fmtUsd(n) {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString("uk-UA", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function phaseLabel(phase, t) {
  if (phase === "sp") return t("orderBessPhase1p");
  if (phase === "tp") return t("orderBessPhase3p");
  return "";
}

function fmtUah(n) {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString("uk-UA", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function skuKey(a) {
  return String(a || "")
    .toUpperCase()
    .replace(/[\s\-_]+/g, "")
    .replace(/[^A-Z0-9.]/g, "");
}

/** Google Images search for a catalog name (udm=2 is the image results tab). */
function googleImagesUrl(name) {
  const params = new URLSearchParams({
    udm: "2",
    q: name,
  });
  return `https://www.google.com/search?${params.toString()}`;
}

const productThumbCache = new Map();

function ProductThumb({ name, article, imageUrl }) {
  const local =
    typeof imageUrl === "string" && imageUrl.startsWith("/") ? imageUrl : "";
  const cacheKey = local || name;
  const [src, setSrc] = useState(() => productThumbCache.get(cacheKey) || "");
  const [failed, setFailed] = useState(false);
  const [zoom, setZoom] = useState(null);

  useEffect(() => {
    if (local) {
      productThumbCache.set(cacheKey, local);
      setSrc(local);
      setFailed(false);
      return undefined;
    }
    if (!name || productThumbCache.has(name)) {
      setSrc(productThumbCache.get(name) || "");
      return undefined;
    }
    let cancelled = false;
    const params = new URLSearchParams({ q: name });
    fetch(apiUrl(`/api/bess-order/image-preview?${params}`))
      .then((res) => (res.ok ? res.json() : { images: [] }))
      .then((data) => {
        const url = (data.images && data.images[0]) || "";
        productThumbCache.set(name, url);
        if (!cancelled) setSrc(url);
      })
      .catch(() => {
        productThumbCache.set(name, "");
        if (!cancelled) setSrc("");
      });
    return () => {
      cancelled = true;
    };
  }, [name, local, cacheKey]);

  const showZoom = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const size = 240;
    let left = rect.right + 12;
    let top = rect.top + rect.height / 2 - size / 2;
    if (left + size > window.innerWidth - 8) left = rect.left - size - 12;
    if (top < 8) top = 8;
    if (top + size > window.innerHeight - 8)
      top = window.innerHeight - size - 8;
    setZoom({ top, left, size });
  };

  if (!src || failed) {
    return <span className="order-bess-mono">{article}</span>;
  }
  return (
    <>
      <a
        className="order-bess-thumb"
        href={googleImagesUrl(name)}
        target="_blank"
        rel="noreferrer"
        aria-label={article}
        onMouseEnter={showZoom}
        onMouseLeave={() => setZoom(null)}
        onFocus={showZoom}
        onBlur={() => setZoom(null)}
      >
        <img src={src} alt={name} onError={() => setFailed(true)} />
      </a>
      {zoom ? (
        <span
          className="order-bess-thumb-zoom"
          style={{
            top: zoom.top,
            left: zoom.left,
            width: zoom.size,
            height: zoom.size,
          }}
          aria-hidden="true"
        >
          <img src={src} alt="" />
        </span>
      ) : null}
    </>
  );
}

/** Whole-kit USD. Null when any line has no price for this business type. */
function bomTotalUsd(lines, items, businessType) {
  if (!lines?.length) return null;
  let sum = 0;
  for (const line of lines) {
    const unit = unitPriceUsd(findItem(items, line.article), businessType);
    if (unit == null) return null;
    sum += unit * (Number(line.qty) || 0);
  }
  return Math.round(sum * 100) / 100;
}

/** Whole-kit USD per kWh. Null when any line has no price. */
function bomUsdPerKwh(lines, kwh, items, businessType) {
  const cap = Number(kwh) || 0;
  const total = bomTotalUsd(lines, items, businessType);
  if (total == null || cap <= 0) return null;
  return Math.round((total / cap) * 100) / 100;
}

/**
 * Price strength from a comparison with the other kits.
 * 0.16 is the cheapest (b2b blue), 1 is the dearest (b2b violet).
 */
function vyriiPriceAlpha(value, samples) {
  const rates = samples.filter((n) => typeof n === "number" && n > 0);
  if (value == null || rates.length < 2) return null;
  const min = Math.min(...rates);
  const max = Math.max(...rates);
  if (!(max > min)) return 1;
  const t = Math.min(1, Math.max(0, (value - min) / (max - min)));
  const floor = 0.16;
  return Math.round((floor + t * (1 - floor)) * 1000) / 1000;
}

function findItem(items, article) {
  const key = skuKey(article);
  if (!key) return null;
  const list = items || [];
  const exact = list.find((it) => skuKey(it.article) === key);
  if (exact) return exact;
  let best = null;
  let bestLen = 0;
  for (const it of list) {
    const ik = skuKey(it.article);
    if (!ik) continue;
    if (
      (key.startsWith(ik) || ik.startsWith(key)) &&
      Math.min(key.length, ik.length) >= 8
    ) {
      const n = Math.min(key.length, ik.length);
      if (n > bestLen) {
        best = it;
        bestLen = n;
      }
    }
  }
  return best;
}

/** Hide a preset when any line has no inbound date in the price list. */
function presetHasNoArrival(preset, items) {
  if (!items?.length || !preset?.lines?.length) return false;
  return preset.lines.some((line) =>
    hasNoArrivalDates(findItem(items, line.article)),
  );
}

function findBatteryKey(raw) {
  const key = skuKey(raw);
  return Object.keys(BATTERY_MODELS).find((a) => skuKey(a) === key) || null;
}

function readOrderBessFromUrl() {
  if (typeof window === "undefined") return {};
  try {
    const u = new URLSearchParams(window.location.search);
    const out = {};
    const biz = (u.get("biz") || "").trim();
    if (VALID_BIZ.has(biz)) out.businessType = biz;
    const preset = (u.get("preset") || "").trim();
    if (preset === "sigen-50-60") out.presetId = "sigen-biz-min";
    else if (VALID_PRESETS.has(preset)) out.presetId = preset;
    const brand = (u.get("brand") || "").trim();
    if (brand === "deye" || brand === "sigen") out.customBrand = brand;
    const inv = (u.get("inv") || "").trim();
    if (INVERTERS[inv]) out.customInv = inv;
    const bat = findBatteryKey(u.get("bat") || "");
    if (bat) out.customBat = bat;
    const kwhRaw = u.get("kwh");
    if (kwhRaw != null && kwhRaw !== "") {
      const kwh = Number(kwhRaw);
      if (Number.isFinite(kwh) && kwh > 0) out.customKwh = kwh;
    }
    const sinv = (u.get("sinv") || "").trim();
    if (SIGEN_INVERTERS[sinv]) out.sigenInv = sinv;
    const sbat = (u.get("sbat") || "").trim();
    if (SIGEN_BATTERIES[sbat]) out.sigenBat = sbat;
    const skwhRaw = u.get("skwh");
    if (skwhRaw != null && skwhRaw !== "") {
      const skwh = Number(skwhRaw);
      if (Number.isFinite(skwh) && skwh > 0) out.sigenKwh = skwh;
    }
    // Legacy share links used a fixed Sigenergy preset id.
    const legacySigen = (u.get("sigen") || "").trim();
    if (legacySigen && SIGENERGY_PRESETS.some((p) => p.id === legacySigen)) {
      out.customBrand = "sigen";
      const preset = SIGENERGY_PRESETS.find((p) => p.id === legacySigen);
      if (preset) {
        const invLine = preset.lines.find((l) => SIGEN_INVERTERS[l.article]);
        const batLine = preset.lines.find((l) => SIGEN_BATTERIES[l.article]);
        if (invLine) out.sigenInv = invLine.article;
        if (batLine) out.sigenBat = batLine.article;
        out.sigenKwh = preset.kwh;
      }
    }
    const unitsRaw = u.get("units");
    if (unitsRaw != null && unitsRaw !== "") {
      const units = Number.parseInt(unitsRaw, 10);
      if (DISCOUNT_UNITS.includes(units)) out.discountUnits = units;
    }
    return out;
  } catch {
    return {};
  }
}

function writeOrderBessToUrl(state) {
  if (typeof window === "undefined") return;
  try {
    const u = new URL(window.location.href);
    u.searchParams.set("biz", state.businessType);
    u.searchParams.set("preset", state.presetId);
    u.searchParams.delete("sigen");
    if (state.presetId === CUSTOM_PRESET_ID) {
      u.searchParams.set("brand", state.customBrand || "deye");
      if (state.customBrand === "sigen") {
        u.searchParams.set("sinv", state.sigenInv);
        u.searchParams.set("sbat", state.sigenBat);
        u.searchParams.set("skwh", String(state.sigenKwh));
        u.searchParams.delete("inv");
        u.searchParams.delete("bat");
        u.searchParams.delete("kwh");
      } else {
        u.searchParams.delete("sinv");
        u.searchParams.delete("sbat");
        u.searchParams.delete("skwh");
        u.searchParams.set("inv", state.customInv);
        u.searchParams.set("bat", state.customBat);
        u.searchParams.set("kwh", String(state.customKwh));
      }
    } else {
      u.searchParams.delete("brand");
      u.searchParams.delete("sinv");
      u.searchParams.delete("sbat");
      u.searchParams.delete("skwh");
      u.searchParams.delete("inv");
      u.searchParams.delete("bat");
      u.searchParams.delete("kwh");
    }
    u.searchParams.set("units", String(state.discountUnits));
    const next = `${u.pathname}${u.search}${u.hash}`;
    const cur = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    if (next !== cur) window.history.replaceState({}, "", next);
  } catch {
    /* ignore */
  }
}

function ShareIcon({ className }) {
  return (
    <svg
      className={className}
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="18" cy="5" r="3" />
      <circle cx="6" cy="12" r="3" />
      <circle cx="18" cy="19" r="3" />
      <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
      <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
    </svg>
  );
}

export default function OrderBessPage({ t }) {
  const initialUrl = useMemo(() => readOrderBessFromUrl(), []);

  const [businessType, setBusinessType] = useState(
    initialUrl.businessType || "cash",
  );
  const [presetId, setPresetId] = useState(initialUrl.presetId || "hv-50-60");
  const [priceList, setPriceList] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [loading, setLoading] = useState(true);

  // Custom builder state
  const [customInv, setCustomInv] = useState(
    initialUrl.customInv || "SUN-50K-SG01HP3-EU-BM4",
  );
  const [customBat, setCustomBat] = useState(
    initialUrl.customBat || "BAHV-100512-LFP",
  );
  const [customKwh, setCustomKwh] = useState(
    initialUrl.customKwh != null ? initialUrl.customKwh : 61.44,
  );
  const [customBrand, setCustomBrand] = useState(
    initialUrl.customBrand || "deye",
  );
  const [sigenInv, setSigenInv] = useState(
    initialUrl.sigenInv || "SigenStor EC 10.0 TP",
  );
  const [sigenBat, setSigenBat] = useState(
    initialUrl.sigenBat || "SigenStor BAT 10.0",
  );
  const [sigenKwh, setSigenKwh] = useState(
    initialUrl.sigenKwh != null ? initialUrl.sigenKwh : 20,
  );

  const [discountUnits] = useState(initialUrl.discountUnits || 2);
  const [contactName, setContactName] = useState("");
  const [contactPhone, setContactPhone] = useState("");
  const [contactFormError, setContactFormError] = useState("");
  const [pdfBusy, setPdfBusy] = useState(false);
  const [buyBusy, setBuyBusy] = useState(false);
  const [buySent, setBuySent] = useState(false);
  const [shareModalOpen, setShareModalOpen] = useState(false);
  const [shareModalUrl, setShareModalUrl] = useState("");
  const [shareModalCopied, setShareModalCopied] = useState(false);
  const [shareModalCopyFailed, setShareModalCopyFailed] = useState(false);

  const loadPrices = useCallback(async (refresh = false) => {
    setLoading(true);
    setLoadError("");
    try {
      const q = refresh ? "?refresh=true" : "";
      const res = await fetch(apiUrl(`/api/bess-order/price-list${q}`), {
        cache: "no-store",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setPriceList(data);
    } catch (e) {
      setLoadError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadPrices(false);
  }, [loadPrices]);

  useEffect(() => {
    writeOrderBessToUrl({
      businessType,
      presetId,
      customBrand,
      customInv,
      customBat,
      customKwh,
      sigenInv,
      sigenBat,
      sigenKwh,
      discountUnits,
    });
  }, [
    businessType,
    presetId,
    customBrand,
    customInv,
    customBat,
    customKwh,
    sigenInv,
    sigenBat,
    sigenKwh,
    discountUnits,
  ]);

  const handleShare = useCallback(async () => {
    writeOrderBessToUrl({
      businessType,
      presetId,
      customBrand,
      customInv,
      customBat,
      customKwh,
      sigenInv,
      sigenBat,
      sigenKwh,
      discountUnits,
    });
    const payload = await buildSharePageModalPayload();
    if (!payload) return;
    setShareModalUrl(payload.url);
    setShareModalCopied(payload.copied);
    setShareModalCopyFailed(payload.copyFailed);
    setShareModalOpen(true);
  }, [
    businessType,
    presetId,
    customBrand,
    customInv,
    customBat,
    customKwh,
    sigenInv,
    sigenBat,
    sigenKwh,
    discountUnits,
  ]);

  const invMeta = INVERTERS[customInv];
  const voltageClass = invMeta?.voltage === "hv" ? "hv" : "lv";

  const batteryChoices = useMemo(() => {
    return Object.entries(BATTERY_MODELS)
      .filter(([, m]) => {
        if (voltageClass === "lv") return m.voltage === "lv";
        return m.voltage === "hv1" || m.voltage === "hv3";
      })
      .map(([article, m]) => ({
        article,
        ...m,
        noArrival: hasNoArrivalDates(findItem(priceList?.items, article)),
      }));
  }, [voltageClass, priceList]);

  const inverterChoices = useMemo(() => {
    return Object.entries(INVERTERS).map(([article, meta]) => ({
      article,
      ...meta,
      noArrival: hasNoArrivalDates(findItem(priceList?.items, article)),
    }));
  }, [priceList]);

  useEffect(() => {
    // Keep battery model compatible when inverter voltage class changes;
    // skip SKUs with no inbound/arrival dates («дані про приходи відсутні»).
    const selectable = batteryChoices.filter((b) => !b.noArrival);
    const pool = selectable.length ? selectable : batteryChoices;
    if (!pool.some((b) => b.article === customBat)) {
      setCustomBat(pool[0]?.article || "");
    }
  }, [batteryChoices, customBat]);

  useEffect(() => {
    const selectable = inverterChoices.filter((i) => !i.noArrival);
    const pool = selectable.length ? selectable : inverterChoices;
    if (!pool.some((i) => i.article === customInv)) {
      setCustomInv(pool[0]?.article || customInv);
    }
  }, [inverterChoices, customInv]);

  const kwhOptions = useMemo(() => {
    if (!customBat) return [];
    return allowedKwhOptions(customBat, voltageClass);
  }, [customBat, voltageClass]);

  useEffect(() => {
    if (!kwhOptions.length) return;
    if (!kwhOptions.some((o) => Math.abs(o.kwh - customKwh) < 0.01)) {
      const closest = kwhOptions.reduce((best, o) =>
        !best || Math.abs(o.kwh - customKwh) < Math.abs(best.kwh - customKwh)
          ? o
          : best,
      );
      setCustomKwh(closest.kwh);
    }
  }, [kwhOptions, customKwh]);

  const sigenInvMeta = SIGEN_INVERTERS[sigenInv];

  const selectedPhase = useMemo(() => {
    if (presetId === CUSTOM_PRESET_ID) {
      if (customBrand === "sigen") return sigenInvMeta?.phase || "";
      return invMeta?.phase || "";
    }
    const preset = ALL_PRESETS.find((p) => p.id === presetId);
    const invLine = preset?.lines?.find(
      (l) => SIGEN_INVERTERS[l.article] || INVERTERS[l.article],
    );
    if (!invLine) return "";
    return (
      SIGEN_INVERTERS[invLine.article]?.phase ||
      INVERTERS[invLine.article]?.phase ||
      ""
    );
  }, [presetId, customBrand, sigenInvMeta, invMeta]);

  const sigenInverterChoices = useMemo(
    () =>
      Object.entries(SIGEN_INVERTERS).map(([article, meta]) => ({
        article,
        ...meta,
      })),
    [],
  );

  const sigenBatFamily = sigenCompatibleBatteryFamily(sigenInv);
  const sigenBatteryChoices = useMemo(
    () =>
      Object.entries(SIGEN_BATTERIES)
        .filter(([, m]) => m.family === sigenBatFamily)
        .map(([article, m]) => ({ article, ...m })),
    [sigenBatFamily],
  );

  useEffect(() => {
    if (!sigenBatteryChoices.some((b) => b.article === sigenBat)) {
      setSigenBat(sigenBatteryChoices[0]?.article || "");
    }
  }, [sigenBatteryChoices, sigenBat]);

  const sigenKwhOpts = useMemo(() => {
    if (!sigenInv || !sigenBat) return [];
    return sigenKwhOptions(sigenInv, sigenBat);
  }, [sigenInv, sigenBat]);

  useEffect(() => {
    if (!sigenKwhOpts.length) return;
    if (!sigenKwhOpts.some((o) => Math.abs(o.kwh - sigenKwh) < 0.01)) {
      const closest = sigenKwhOpts.reduce((best, o) =>
        !best || Math.abs(o.kwh - sigenKwh) < Math.abs(best.kwh - sigenKwh)
          ? o
          : best,
      );
      setSigenKwh(closest.kwh);
    }
  }, [sigenKwhOpts, sigenKwh]);

  const activeBom = useMemo(() => {
    if (presetId === CUSTOM_PRESET_ID && customBrand === "sigen") {
      return buildSigenBom(sigenInv, sigenBat, sigenKwh);
    }
    if (presetId === CUSTOM_PRESET_ID) {
      return buildCustomBom(customInv, customBat, customKwh);
    }
    const p = ALL_PRESETS.find((x) => x.id === presetId);
    if (!p) return { lines: [], kwh: 0, kw: 0, voltageClass: "" };
    return {
      lines: p.lines,
      kwh: p.kwh,
      kw: p.kw,
      voltageClass: p.group,
      meta: {},
    };
  }, [
    presetId,
    customBrand,
    customInv,
    customBat,
    customKwh,
    sigenInv,
    sigenBat,
    sigenKwh,
  ]);

  const pricedLines = useMemo(() => {
    const items = priceList?.items || [];
    return (activeBom.lines || []).map((l) => {
      const item = findItem(items, l.article);
      const unit = unitPriceUsd(item, businessType);
      const lineTotal =
        unit == null ? null : Math.round(unit * l.qty * 100) / 100;
      const availability =
        item?.availabilityInstaller || item?.availability || "";
      const priceSource = isEtuVendor(item)
        ? "etu"
        : businessType === "cash"
          ? item?.priceSourceCash || ""
          : item?.priceSourceRetail || "";
      return {
        ...l,
        name: item?.name || l.article,
        imageUrl: item?.imageUrl || "",
        brand: item?.brand || "",
        code: item?.code || "",
        unit,
        lineTotal,
        availability,
        priceSource,
        missing: !item || unit == null,
      };
    });
  }, [activeBom, priceList, businessType]);

  const totalUsd = useMemo(() => {
    if (pricedLines.some((l) => l.lineTotal == null)) return null;
    return (
      Math.round(
        pricedLines.reduce((s, l) => s + (l.lineTotal || 0), 0) * 100,
      ) / 100
    );
  }, [pricedLines]);

  const fx = priceList?.fxRate || 45.3;
  const totalUah =
    totalUsd == null ? null : Math.round(totalUsd * fx * 100) / 100;

  const bizMeta = BUSINESS_TYPES.find((b) => b.id === businessType);
  const priceColLabel = t(bizMeta?.priceLabelKey || "orderBessPriceUsd");

  const usdPerKwh = useMemo(() => {
    const kwh = Number(activeBom.kwh) || 0;
    if (totalUsd == null || kwh <= 0) return null;
    return Math.round((totalUsd / kwh) * 100) / 100;
  }, [totalUsd, activeBom.kwh]);

  const perkwhAlpha = useMemo(() => {
    const items = priceList?.items || [];
    if (!items.length || usdPerKwh == null) return null;
    const samples = ALL_PRESETS.filter(
      (p) => !presetHasNoArrival(p, items),
    ).map((p) => bomUsdPerKwh(p.lines, p.kwh, items, businessType));
    samples.push(usdPerKwh);
    return vyriiPriceAlpha(usdPerKwh, samples);
  }, [priceList, businessType, usdPerKwh]);

  const offerTitle = useMemo(() => {
    const kw = activeBom.kw || 0;
    const kwh = activeBom.kwh || 0;
    const price = totalUsd == null ? "—" : `$${fmtUsd(totalUsd)}`;
    const brand =
      presetId === CUSTOM_PRESET_ID
        ? customBrand === "sigen"
          ? "Sigenergy"
          : "Deye"
        : presetBrand(ALL_PRESETS.find((x) => x.id === presetId));
    return t("orderBessOfferTitle", {
      brand,
      kw,
      kwh: Math.round(kwh),
      price,
    });
  }, [activeBom, presetId, customBrand, totalUsd, t]);

  const homePresets = useMemo(
    () =>
      ALL_PRESETS.filter(
        (p) =>
          presetSegment(p) === "home" &&
          !presetHasNoArrival(p, priceList?.items),
      ).sort((a, b) => a.kw - b.kw || a.kwh - b.kwh),
    [priceList],
  );
  const bizPresets = useMemo(
    () =>
      ALL_PRESETS.filter(
        (p) =>
          presetSegment(p) === "biz" &&
          !presetHasNoArrival(p, priceList?.items),
      ).sort((a, b) => a.kw - b.kw || a.kwh - b.kwh),
    [priceList],
  );

  useEffect(() => {
    const items = priceList?.items;
    if (!items?.length || presetId === CUSTOM_PRESET_ID) return;
    const current = ALL_PRESETS.find((p) => p.id === presetId);
    if (!current || !presetHasNoArrival(current, items)) return;
    const visible = ALL_PRESETS.filter((p) => !presetHasNoArrival(p, items));
    const sameSegment = visible.filter(
      (p) => presetSegment(p) === presetSegment(current),
    );
    const next = sameSegment[0] || visible[0];
    if (next) setPresetId(next.id);
  }, [priceList, presetId]);

  const biomSavings = useMemo(() => {
    if (presetId !== CUSTOM_PRESET_ID || customBrand === "sigen") return null;
    return computeBiomSavings({
      inverterArticle: customInv,
      batteryArticle: customBat,
      targetKwh: customKwh,
      businessType,
      priceItems: priceList?.items || [],
      findItemFn: findItem,
    });
  }, [
    presetId,
    customBrand,
    customInv,
    customBat,
    customKwh,
    businessType,
    priceList,
  ]);

  const kitPayload = useMemo(
    () => ({
      kw: activeBom.kw,
      kwh: activeBom.kwh,
      ...(presetId === CUSTOM_PRESET_ID
        ? customBrand === "sigen"
          ? {
              brand: "sigen",
              inv: sigenInv,
              bat: sigenBat,
              inverter: sigenInv,
              battery: sigenBat,
            }
          : {
              brand: "deye",
              inv: customInv,
              bat: customBat,
              inverter: customInv,
              battery: customBat,
            }
        : {}),
      lines: pricedLines.map((l) => ({
        article: l.article,
        qty: l.qty,
        unit: l.unit,
        lineTotal: l.lineTotal,
      })),
    }),
    [
      activeBom,
      pricedLines,
      presetId,
      customBrand,
      customInv,
      customBat,
      sigenInv,
      sigenBat,
    ],
  );

  const orderBessPageUrl = useMemo(() => {
    if (typeof window === "undefined") return "";
    try {
      return window.location.href;
    } catch {
      return "";
    }
  }, []);

  const trimmedName = contactName.trim();
  const trimmedPhone = contactPhone.trim();

  const submitBuyRequest = async () => {
    if (buyBusy || buySent) return;
    if (trimmedPhone.length < 5) {
      setContactFormError(t("orderBessContactNeedPhone"));
      return;
    }
    setContactFormError("");
    setBuyBusy(true);
    try {
      const res = await fetch(apiUrl("/api/bess-order/buy-request"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          preset_id: presetId,
          business_type: businessType,
          total_usd: totalUsd,
          name: trimmedName || null,
          phone: trimmedPhone,
          kit: kitPayload,
          page_url:
            typeof window !== "undefined"
              ? window.location.href
              : orderBessPageUrl,
        }),
      });
      if (!res.ok) throw new Error(`buy request ${res.status}`);
      setBuySent(true);
    } catch {
      setContactFormError(t("orderBessBuyFailed"));
    } finally {
      setBuyBusy(false);
    }
  };

  const downloadPng = async () => {
    if (totalUsd == null || pdfBusy) return;
    setPdfBusy(true);
    try {
      await downloadOrderBessOfferPng({
        kw: activeBom.kw,
        kwh: activeBom.kwh,
        lines: pricedLines,
        totalUsd,
        totalUah,
        usdPerKwh,
        usdPerKwhAlpha: perkwhAlpha,
        fxRate: fx,
        priceLabel: priceColLabel,
      });
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error("Order BESS PNG failed", e);
    } finally {
      setPdfBusy(false);
    }
  };

  return (
    <div className="order-bess-page">
      <div className="order-bess-page__inner">
        <header className="order-bess-hero">
          <h1 className="order-bess-hero__title">{t("orderBessPageTitle")}</h1>
          <p className="order-bess-hero__sub">{t("orderBessPageSubtitle")}</p>
        </header>

        <section className="order-bess-card" aria-labelledby="order-bess-biz">
          <h2 id="order-bess-biz" className="order-bess-card__title">
            {t("orderBessBusinessType")}
          </h2>
          <div
            className="order-bess-seg"
            role="radiogroup"
            aria-label={t("orderBessBusinessType")}
          >
            {BUSINESS_TYPES.map((b) => (
              <button
                key={b.id}
                type="button"
                role="radio"
                aria-checked={businessType === b.id}
                className={`order-bess-seg__btn${businessType === b.id ? " order-bess-seg__btn--active" : ""}`}
                onClick={() => setBusinessType(b.id)}
              >
                {t(b.labelKey)}
              </button>
            ))}
          </div>
        </section>

        <section
          className="order-bess-card"
          aria-labelledby="order-bess-preset"
        >
          <h2 id="order-bess-preset" className="order-bess-card__title">
            {t("orderBessPreset")}
          </h2>
          <div className="order-bess-presets">
            <div className="order-bess-presets__group">
              <div className="order-bess-presets__label">
                {t("orderBessPresetSigenHome")}
              </div>
              <div className="order-bess-chips">
                {homePresets.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    className={`order-bess-chip${presetId === p.id ? " order-bess-chip--active" : ""}`}
                    onClick={() => setPresetId(p.id)}
                  >
                    {presetBrand(p)} · {p.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="order-bess-presets__group">
              <div className="order-bess-presets__label">
                {t("orderBessPresetSigenBiz")}
              </div>
              <div className="order-bess-chips">
                {bizPresets.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    className={`order-bess-chip${presetId === p.id ? " order-bess-chip--active" : ""}`}
                    onClick={() => setPresetId(p.id)}
                  >
                    {presetBrand(p)} · {p.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="order-bess-presets__group">
              <div className="order-bess-presets__label">
                {t("orderBessPresetCustom")}
              </div>
              <button
                type="button"
                className={`order-bess-chip${presetId === CUSTOM_PRESET_ID ? " order-bess-chip--active" : ""}`}
                onClick={() => setPresetId(CUSTOM_PRESET_ID)}
              >
                {t("orderBessCustomBtn")}
              </button>
            </div>
          </div>

          {presetId === CUSTOM_PRESET_ID ? (
            <div className="order-bess-custom">
              <label className="order-bess-field">
                <span>{t("orderBessSelectBrand")}</span>
                <select
                  value={customBrand}
                  onChange={(e) => setCustomBrand(e.target.value)}
                >
                  <option value="deye">Deye</option>
                  <option value="sigen">Sigenergy</option>
                </select>
              </label>
              {customBrand === "sigen" ? (
                <>
                  <label className="order-bess-field">
                    <span>{t("orderBessSelectKw")}</span>
                    <select
                      value={sigenInv}
                      onChange={(e) => setSigenInv(e.target.value)}
                    >
                      <optgroup label={t("orderBessPresetSigenHome")}>
                        {sigenInverterChoices
                          .filter((inv) => inv.line === "home")
                          .map((inv) => (
                            <option key={inv.article} value={inv.article}>
                              {inv.kw} кВт · {phaseLabel(inv.phase, t)} —{" "}
                              {inv.article}
                            </option>
                          ))}
                      </optgroup>
                      <optgroup label={t("orderBessPresetSigenBiz")}>
                        {sigenInverterChoices
                          .filter((inv) => inv.line === "biz")
                          .map((inv) => (
                            <option key={inv.article} value={inv.article}>
                              {inv.kw} кВт · {phaseLabel(inv.phase, t)} —{" "}
                              {inv.article}
                            </option>
                          ))}
                      </optgroup>
                    </select>
                  </label>
                  <label className="order-bess-field">
                    <span>{t("orderBessSelectBattery")}</span>
                    <select
                      value={sigenBat}
                      onChange={(e) => setSigenBat(e.target.value)}
                    >
                      {sigenBatteryChoices.map((b) => (
                        <option key={b.article} value={b.article}>
                          {b.article} ({b.kwh} кВт·год)
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="order-bess-range-hint">
                    {t("orderBessAllowedKwh")}:{" "}
                    <strong>{kwhRangeLabel(sigenKwhOpts)}</strong>
                    {activeBom?.meta?.modules ? (
                      <span className="order-bess-range-hint__note">
                        {" "}
                        {t("orderBessSigenModulesNote", {
                          count: activeBom.meta.modules,
                        })}
                      </span>
                    ) : null}
                  </div>
                  <label className="order-bess-field">
                    <span>{t("orderBessSelectKwh")}</span>
                    <select
                      value={String(sigenKwh)}
                      onChange={(e) => setSigenKwh(Number(e.target.value))}
                    >
                      {sigenKwhOpts.map((o) => (
                        <option key={`${o.kwh}-${o.modules}`} value={o.kwh}>
                          {o.kwh} кВт·год ({o.modules} шт.)
                        </option>
                      ))}
                    </select>
                  </label>
                </>
              ) : (
                <>
                  <label className="order-bess-field">
                    <span>{t("orderBessSelectKw")}</span>
                    <select
                      value={customInv}
                      onChange={(e) => {
                        const next = inverterChoices.find(
                          (i) => i.article === e.target.value,
                        );
                        if (next?.noArrival) return;
                        setCustomInv(e.target.value);
                      }}
                    >
                      {inverterChoices.map((inv) => (
                        <option
                          key={inv.article}
                          value={inv.article}
                          disabled={inv.noArrival}
                        >
                          {inv.kw} кВт · {phaseLabel(inv.phase, t)} (
                          {inv.voltage.toUpperCase()}) — {inv.article}
                          {inv.noArrival
                            ? ` — ${t("orderBessNoArrivalDates")}`
                            : ""}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="order-bess-field">
                    <span>{t("orderBessSelectBattery")}</span>
                    <select
                      value={customBat}
                      onChange={(e) => {
                        const next = batteryChoices.find(
                          (b) => b.article === e.target.value,
                        );
                        if (next?.noArrival) return;
                        setCustomBat(e.target.value);
                      }}
                    >
                      {batteryChoices.map((b) => (
                        <option
                          key={b.article}
                          value={b.article}
                          disabled={b.noArrival}
                        >
                          {b.label}
                          {b.noArrival
                            ? ` — ${t("orderBessNoArrivalDates")}`
                            : ""}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="order-bess-range-hint">
                    {t("orderBessAllowedKwh")}:{" "}
                    <strong>{kwhRangeLabel(kwhOptions)}</strong>
                    {voltageClass === "hv" ? (
                      <span className="order-bess-range-hint__note">
                        {" "}
                        {t("orderBessHvVoltageNote")}
                      </span>
                    ) : null}
                  </div>
                  <label className="order-bess-field">
                    <span>{t("orderBessSelectKwh")}</span>
                    <select
                      value={String(customKwh)}
                      onChange={(e) => setCustomKwh(Number(e.target.value))}
                    >
                      {kwhOptions.map((o) => (
                        <option key={`${o.kwh}-${o.modules}`} value={o.kwh}>
                          {o.kwh} кВт·год
                          {o.voltageV != null
                            ? ` (${o.strings}×${o.modulesPerString} @ ${o.voltageV} V)`
                            : ` (${o.modules} шт.)`}
                        </option>
                      ))}
                    </select>
                  </label>
                </>
              )}
            </div>
          ) : null}
        </section>

        <section className="order-bess-card" aria-labelledby="order-bess-bom">
          <div className="order-bess-card__head">
            <h2 id="order-bess-bom" className="order-bess-card__title">
              {offerTitle}
              {" · "}
              <span
                className={
                  perkwhAlpha == null
                    ? undefined
                    : "order-bess-perkwh"
                }
                style={
                  perkwhAlpha == null
                    ? undefined
                    : { "--perkwh-alpha": String(perkwhAlpha) }
                }
              >
                {usdPerKwh == null
                  ? `—/${t("orderBessKwhUnit")}`
                  : `$${fmtUsd(usdPerKwh)}/${t("orderBessKwhUnit")}`}
              </span>
            </h2>
            <button
              type="button"
              className="order-bess-refresh"
              onClick={() => void loadPrices(true)}
              disabled={loading}
            >
              {t("orderBessRefreshPrices")}
            </button>
          </div>
          {priceList?.sources?.etu ? (
            <p className="order-bess-muted order-bess-etu-hint">
              {t("orderBessEtuHint")}
            </p>
          ) : null}
          {loading && !priceList ? (
            <p className="order-bess-muted">{t("orderBessLoading")}</p>
          ) : null}
          {loadError ? <p className="order-bess-error">{loadError}</p> : null}

          <div className="order-bess-table-wrap">
            <table className="order-bess-table">
              <thead>
                <tr>
                  <th>{t("orderBessColItem")}</th>
                  <th>{t("orderBessColArticle")}</th>
                  <th>{t("orderBessColQty")}</th>
                  <th>{priceColLabel}</th>
                  <th>{t("orderBessColSum")}</th>
                  <th>{t("orderBessColAvail")}</th>
                </tr>
              </thead>
              <tbody>
                {pricedLines.map((l) => (
                  <tr key={`${l.article}-${l.qty}-${l.note}`}>
                    <td>
                      <div className="order-bess-item-name">
                        <a
                          href={googleImagesUrl(l.name)}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {l.name}
                        </a>
                      </div>
                      {l.note ? (
                        <div className="order-bess-item-note">{l.note}</div>
                      ) : null}
                      {l.priceSource === "etu" ? (
                        <div className="order-bess-item-note">
                          {t("orderBessEtuPriceNote")}
                        </div>
                      ) : null}
                      {biomSavings &&
                      biomSavings.savingsUsd > 0 &&
                      skuKey(l.article) === skuKey(customBat) ? (
                        <div className="order-bess-biom-cheaper">
                          {t("orderBessBiomCheaper", {
                            usd: fmtUsd(biomSavings.savingsUsd),
                            model: biomSavings.biomArticle,
                          })}
                        </div>
                      ) : null}
                    </td>
                    <td>
                      <ProductThumb
                        name={l.name}
                        article={l.article}
                        imageUrl={l.imageUrl}
                      />
                    </td>
                    <td className="order-bess-num">{l.qty}</td>
                    <td className="order-bess-num">
                      {l.unit == null ? "—" : `$${fmtUsd(l.unit)}`}
                    </td>
                    <td className="order-bess-num">
                      {l.lineTotal == null ? "—" : `$${fmtUsd(l.lineTotal)}`}
                    </td>
                    <td>
                      {l.availability ? (
                        <span
                          className={
                            /в\s*наявност/i.test(l.availability)
                              ? "order-bess-avail order-bess-avail--in-stock"
                              : "order-bess-avail"
                          }
                        >
                          {l.availability}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td colSpan={4}>
                    <strong>{t("orderBessTotal")}</strong>
                    <span className="order-bess-muted"> · {priceColLabel}</span>
                  </td>
                  <td className="order-bess-num">
                    <strong>
                      {totalUsd == null ? "—" : `$${fmtUsd(totalUsd)}`}
                    </strong>
                  </td>
                  <td />
                </tr>
                <tr>
                  <td colSpan={4}>{t("orderBessTotalUah", { rate: fx })}</td>
                  <td className="order-bess-num">
                    {totalUah == null ? "—" : `${fmtUah(totalUah)} грн`}
                  </td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
          <p className="order-bess-kwh">
            {t("orderBessCapacity")}: <strong>{activeBom.kwh} кВт·год</strong> ·{" "}
            {activeBom.kw} кВт
            {selectedPhase ? ` · ${phaseLabel(selectedPhase, t)}` : ""}
          </p>
        </section>

        <section
          className="order-bess-card"
          aria-labelledby="order-bess-summary"
        >
          <div className="order-bess-card__head">
            <h2 id="order-bess-summary" className="order-bess-card__title">
              {t("orderBessSummary")}
            </h2>
            <div className="order-bess-summary-actions">
              <button
                type="button"
                className="order-bess-primary"
                disabled={pdfBusy || totalUsd == null}
                onClick={() => void downloadPng()}
              >
                {pdfBusy ? t("orderBessPngBusy") : t("orderBessDownloadPng")}
              </button>
            </div>
          </div>
          <ul className="order-bess-summary-list">
            <li>
              {t("orderBessSummaryKit")}: {activeBom.kw} кВт + {activeBom.kwh}{" "}
              кВт·год
              {selectedPhase ? ` · ${phaseLabel(selectedPhase, t)}` : ""}
            </li>
            <li>
              {t("orderBessSummaryTotal")}:{" "}
              {totalUsd == null ? "—" : `$${fmtUsd(totalUsd)}`} ({priceColLabel}
              )
            </li>
            <li>
              {t("orderBessSummaryPerKwh")}:{" "}
              {usdPerKwh == null ? (
                "—"
              ) : (
                <span
                  className={
                    perkwhAlpha == null ? undefined : "order-bess-perkwh"
                  }
                  style={
                    perkwhAlpha == null
                      ? undefined
                      : { "--perkwh-alpha": String(perkwhAlpha) }
                  }
                >
                  ${fmtUsd(usdPerKwh)}
                </span>
              )}
            </li>
            <li>
              {t("orderBessSummaryItems")}: {pricedLines.length}
            </li>
          </ul>

          <div className="order-bess-contact">
            <p className="order-bess-contact__label">
              {t("orderBessWantOffer")}
            </p>
            <div className="order-bess-contact-fields">
              <label className="order-bess-field order-bess-field--grow">
                <span>{t("orderBessContactName")}</span>
                <input
                  type="text"
                  autoComplete="name"
                  value={contactName}
                  onChange={(e) => {
                    setContactName(e.target.value);
                    if (contactFormError) setContactFormError("");
                  }}
                  placeholder={t("orderBessContactNamePh")}
                />
              </label>
              <label className="order-bess-field order-bess-field--grow">
                <span>{t("orderBessContactPhone")}</span>
                <input
                  type="tel"
                  autoComplete="tel"
                  value={contactPhone}
                  onChange={(e) => {
                    setContactPhone(e.target.value);
                    if (contactFormError) setContactFormError("");
                    if (buySent) setBuySent(false);
                  }}
                  placeholder={t("orderBessContactPhonePh")}
                />
              </label>
            </div>
            {contactFormError ? (
              <p className="order-bess-error">{contactFormError}</p>
            ) : null}
            {buySent ? (
              <p className="order-bess-ok" role="status">
                {t("orderBessBuyOk")}
              </p>
            ) : (
              <div className="order-bess-contact__btns">
                <button
                  type="button"
                  className="order-bess-buy-btn"
                  disabled={buyBusy}
                  onClick={() => void submitBuyRequest()}
                >
                  {buyBusy ? t("orderBessContactBusy") : t("orderBessBuyBtn")}
                </button>
              </div>
            )}
          </div>
        </section>

        <section
          className="order-bess-card order-bess-share-card"
          aria-labelledby="order-bess-share"
        >
          <h2 id="order-bess-share" className="order-bess-card__title">
            {t("orderBessShareTitle")}
          </h2>
          <p className="order-bess-muted">{t("orderBessShareHint")}</p>
          <button
            type="button"
            className="order-bess-share-btn"
            onClick={() => void handleShare()}
            aria-label={t("orderBessShareBtn")}
          >
            <ShareIcon className="order-bess-share-btn__icon" />
            <span>{t("orderBessShareBtn")}</span>
          </button>
        </section>
      </div>

      <SharePageModal
        open={shareModalOpen}
        url={shareModalUrl}
        copied={shareModalCopied}
        copyFailed={shareModalCopyFailed}
        onClose={() => setShareModalOpen(false)}
        t={t}
      />
    </div>
  );
}
