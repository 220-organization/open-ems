import { useEffect, useMemo, useRef, useState } from "react";
import ChargerBuyRequestModal from "./ChargerBuyRequestModal";
import {
  CommercialHero,
  CommercialMarketingSections,
  commercialLandingFaqJsonLd,
} from "./CommercialChargerLanding";
import { notifyOpenEmsSearchChange } from "./sharePageQr";
import { OPEN_EMS_SITE_URL } from "./seoContent";
import { useOpenEmsSeo } from "./useOpenEmsSeo";
import ChargerCatalogSegmentBar from "./ChargerCatalogSegmentBar";
import "./buy-home-charger.css";
import "./commercial-charger.css";

const EUR_UAH_FALLBACK = 47;
const USD_UAH_FALLBACK = 42;
const CURRENCY_STORAGE_KEY = "commercial-charger-currency";
const DEFAULT_SORT = "price-asc";
/** Random default when the URL has no brand= (Eltis, UGV, EDS, or Infi). */
const DEFAULT_BRAND_POOL = ["eltis", "ugv", "eds", "infi"];
const CATALOG_PATH = "/buy-commercial-charger";

function pickDefaultBrand() {
  const i = Math.floor(Math.random() * DEFAULT_BRAND_POOL.length);
  return DEFAULT_BRAND_POOL[i] || "eltis";
}
const POWER_FILTERS = [
  { id: "40plus", minKw: 40 },
  { id: "120plus", minKw: 120 },
  { id: "160plus", minKw: 160 },
  { id: "240plus", minKw: 240 },
];
const POWER_IDS = POWER_FILTERS.map((item) => item.id);
const LAYOUT_IDS = ["station", "station_dcdc", "split", "split_dcdc"];
const WARRANTY_YEARS = ["1", "2", "3"];
const DOWNTIME_IDS = ["48h", "5d", "10d"];
const MANAGER_IDS = ["yes", "no"];
const BRAND_IDS = ["eltis", "eds", "ugv", "eport", "infi"];
const BRAND_LABEL = {
  eds: "EDS Chargers",
  ugv: "UGV Chargers",
  eport: "E-port",
  infi: "Infi Power",
  eltis: "Eltis",
};

function apiUrl(path) {
  const base = (process.env.REACT_APP_API_BASE_URL || "").replace(/\/$/, "");
  return base ? `${base}${path}` : path;
}

function todayKyivIso() {
  try {
    return new Date().toLocaleDateString("en-CA", { timeZone: "Europe/Kyiv" });
  } catch {
    return new Date().toISOString().slice(0, 10);
  }
}

function readStoredCurrency() {
  try {
    const raw = localStorage.getItem(CURRENCY_STORAGE_KEY);
    if (raw === "UAH" || raw === "USD" || raw === "EUR") return raw;
  } catch {
    /* ignore */
  }
  return "EUR";
}

function writeStoredCurrency(currency) {
  try {
    localStorage.setItem(CURRENCY_STORAGE_KEY, currency);
  } catch {
    /* ignore */
  }
}

function fmtMoney(amount, currency, locale) {
  if (amount == null || Number.isNaN(amount)) return "—";
  const code = currency || "EUR";
  const loc =
    code === "USD"
      ? "en-US"
      : locale === "uk"
        ? "uk-UA"
        : locale === "es"
          ? "es-ES"
          : "en-US";
  try {
    return new Intl.NumberFormat(loc, {
      style: "currency",
      currency: code,
      maximumFractionDigits: 0,
    }).format(amount);
  } catch {
    return `${Math.round(amount)} ${code}`;
  }
}

function toDisplayAmount(price, srcCurrency, displayCurrency, eurUah, usdUah) {
  if (price == null || Number.isNaN(Number(price))) return null;
  const src = (srcCurrency || "EUR").toUpperCase();
  const dest = (displayCurrency || "EUR").toUpperCase();
  const amount = Number(price);
  if (src === dest) return amount;
  if (src === "EUR" && dest === "UAH") {
    if (!(eurUah > 0)) return amount;
    return amount * eurUah;
  }
  if (src === "EUR" && dest === "USD") {
    if (!(eurUah > 0) || !(usdUah > 0)) return amount;
    return (amount * eurUah) / usdUah;
  }
  if (src === "UAH" && dest === "EUR") {
    if (!(eurUah > 0)) return amount;
    return amount / eurUah;
  }
  if (src === "UAH" && dest === "USD") {
    if (!(usdUah > 0)) return amount;
    return amount / usdUah;
  }
  if (src === "USD" && dest === "UAH") {
    if (!(usdUah > 0)) return amount;
    return amount * usdUah;
  }
  if (src === "USD" && dest === "EUR") {
    if (!(eurUah > 0) || !(usdUah > 0)) return amount;
    return (amount * usdUah) / eurUah;
  }
  return amount;
}

function powerFilterLabel(id, t) {
  if (id === "40plus") return t("commercialChargerPower40");
  if (id === "120plus") return t("commercialChargerPower120");
  if (id === "160plus") return t("commercialChargerPower160");
  if (id === "240plus") return t("commercialChargerPower240");
  return id;
}

function meetsPowerFilter(product, filterId) {
  const filter = POWER_FILTERS.find((item) => item.id === filterId);
  if (!filter) return true;
  const raw = product?.power_kw;
  const kw = raw == null || raw === "" ? null : Number(raw);
  if (kw != null && Number.isFinite(kw)) return kw >= filter.minKw;
  return product?.power_bucket === "240plus";
}

function seriesLabel(series, t) {
  if (series === "SPLIT") return t("commercialChargerSeriesSplit");
  if (series === "DISPENSER") return t("commercialChargerSeriesDispenser");
  return series;
}

function portsLabel(ports, t) {
  if (ports === "1dc") return t("commercialChargerPorts1dc");
  if (ports === "2dc") return t("commercialChargerPorts2dc");
  if (ports === "2dc_ac") return t("commercialChargerPorts2dcAc");
  if (ports === "2dc_2ac") return t("commercialChargerPorts2dc2ac");
  if (ports === "3dc") return t("commercialChargerPorts3dc");
  if (ports === "4dc") return t("commercialChargerPorts4dc");
  return ports;
}

function coolingLabel(cooling, t) {
  if (cooling === "air") return t("commercialChargerCoolingAir");
  if (cooling === "liquid") return t("commercialChargerCoolingLiquid");
  return cooling;
}

function warrantyYearsLabel(years, t) {
  if (years === "1" || years === 1) return t("commercialChargerWarranty1");
  if (years === "2" || years === 2) return t("commercialChargerWarranty2");
  if (years === "3" || years === 3) return t("commercialChargerWarranty3");
  return String(years);
}

function downtimeLabel(id, t) {
  if (id === "48h") return t("commercialChargerDowntime48h");
  if (id === "5d") return t("commercialChargerDowntime5d");
  if (id === "10d") return t("commercialChargerDowntime10d");
  return id;
}

function leadTimeLabel(id, t) {
  if (id === "now") return t("commercialChargerLeadTimeNow");
  if (id === "2m") return t("commercialChargerLeadTime2m");
  if (id === "35d") return t("commercialChargerLeadTime35d");
  // Catalog is built to order; fall back to the EDS default when the feed omits it.
  if (!id || id === "2to3m") return t("commercialChargerLeadTime2to3m");
  return id;
}

function managerLabel(id, t) {
  if (id === "yes") return t("commercialChargerManagerYes");
  if (id === "no") return t("commercialChargerManagerNo");
  return id;
}

function managerFilterValue(item) {
  if (item?.dedicated_manager === true) return "yes";
  if (item?.dedicated_manager === false) return "no";
  return "";
}

function brandFilterValue(item) {
  const b = (item?.brand || "").toLowerCase();
  if (b.includes("infi")) return "infi";
  if (b.includes("eltis")) return "eltis";
  if (b.includes("ugv")) return "ugv";
  if (b.includes("e-port") || b.includes("eport")) return "eport";
  if (b.includes("eds")) return "eds";
  return "";
}

function brandLabel(id) {
  return BRAND_LABEL[id] || id;
}

function productLayout(item) {
  if (LAYOUT_IDS.includes(item?.layout)) return item.layout;
  const brand = (item?.brand || "").toLowerCase();
  const series = (item?.series || "").toUpperCase();
  const form = (item?.form || "").toLowerCase();
  if (brand.includes("infi")) return "station_dcdc";
  if (brand.includes("eltis") && series === "DC/DC") return "split_dcdc";
  if (
    (form === "split" || form === "dispenser") &&
    (brand.includes("eds") ||
      brand.includes("e-port") ||
      brand.includes("eport"))
  ) {
    return "split";
  }
  return "station";
}

function layoutLabel(id, t) {
  if (id === "station") return t("commercialChargerLayoutStation");
  if (id === "station_dcdc") return t("commercialChargerLayoutStationDcdc");
  if (id === "split") return t("commercialChargerLayoutSplit");
  if (id === "split_dcdc") return t("commercialChargerLayoutSplitDcdc");
  return id;
}

function readCatalogFromUrl() {
  if (typeof window === "undefined") return {};
  try {
    const u = new URLSearchParams(window.location.search);
    const out = {};
    const sku = (u.get("sku") || "").trim();
    if (sku) out.sku = sku;
    const brand = (u.get("brand") || "").trim().toLowerCase();
    if (BRAND_IDS.includes(brand)) out.brand = brand;
    const power = (u.get("power") || "").trim();
    if (POWER_IDS.includes(power)) out.power = power;
    const layout = (u.get("layout") || "").trim();
    if (LAYOUT_IDS.includes(layout)) out.layout = layout;
    const cooling = (u.get("cooling") || "").trim();
    if (cooling) out.cooling = cooling;
    const warranty = (u.get("warranty") || "").trim();
    if (WARRANTY_YEARS.includes(warranty)) out.warranty = warranty;
    const downtime = (u.get("downtime") || "").trim();
    if (DOWNTIME_IDS.includes(downtime)) out.downtime = downtime;
    const manager = (u.get("manager") || "").trim();
    if (MANAGER_IDS.includes(manager)) out.manager = manager;
    const sort = (u.get("sort") || "").trim();
    if (sort === "price-asc" || sort === "price-desc" || sort === "power-desc")
      out.sort = sort;
    return out;
  } catch {
    return {};
  }
}

function writeCatalogToUrl(state) {
  if (typeof window === "undefined") return;
  try {
    const u = new URL(window.location.href);
    const setOrDel = (key, val) => {
      if (val) u.searchParams.set(key, val);
      else u.searchParams.delete(key);
    };
    setOrDel("sku", state.sku);
    setOrDel("brand", state.brand);
    setOrDel("layout", state.layout);
    u.searchParams.delete("series");
    setOrDel("power", state.power);
    u.searchParams.delete("ports");
    u.searchParams.delete("connector");
    setOrDel("cooling", state.cooling);
    setOrDel("warranty", state.warranty);
    setOrDel("downtime", state.downtime);
    setOrDel("manager", state.manager);
    if (state.sort && state.sort !== DEFAULT_SORT)
      u.searchParams.set("sort", state.sort);
    else u.searchParams.delete("sort");
    const next = `${u.pathname}${u.search}${u.hash}`;
    const cur = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    if (next === cur) return;
    window.history.replaceState({}, "", next);
    notifyOpenEmsSearchChange();
  } catch {
    /* ignore */
  }
}

function productQuotePageUrl(p) {
  if (typeof window === "undefined") return CATALOG_PATH;
  const u = new URL(CATALOG_PATH, window.location.origin);
  const lang = new URLSearchParams(window.location.search).get("lang");
  if (lang) u.searchParams.set("lang", lang);
  if (p.sku) u.searchParams.set("sku", p.sku);
  const brand = brandFilterValue(p);
  if (brand) u.searchParams.set("brand", brand);
  const layout = productLayout(p);
  if (layout) u.searchParams.set("layout", layout);
  if (p.power_bucket) u.searchParams.set("power", p.power_bucket);
  if (p.cooling) u.searchParams.set("cooling", p.cooling);
  if (p.warranty_years)
    u.searchParams.set("warranty", String(p.warranty_years));
  if (p.warranty_downtime) u.searchParams.set("downtime", p.warranty_downtime);
  const manager = managerFilterValue(p);
  if (manager) u.searchParams.set("manager", manager);
  return u.toString();
}

function findSkuCard(sku) {
  if (!sku || typeof document === "undefined") return null;
  const nodes = document.querySelectorAll("[data-charger-sku]");
  for (let i = 0; i < nodes.length; i += 1) {
    if (nodes[i].getAttribute("data-charger-sku") === sku) return nodes[i];
  }
  return null;
}

function Chip({ active, disabled, onClick, children }) {
  return (
    <button
      type="button"
      className={`home-charger-chip${active ? " home-charger-chip--active" : ""}`}
      onClick={onClick}
      disabled={disabled}
      aria-pressed={active}
    >
      {children}
    </button>
  );
}

function buildCommercialJsonLd(t, locale, products) {
  const origin =
    typeof window !== "undefined" && window.location?.origin
      ? window.location.origin
      : OPEN_EMS_SITE_URL;
  const pageUrl = `${origin}${CATALOG_PATH}`;
  const orgId = `${origin}/#organization`;
  const list = Array.isArray(products) ? products.slice(0, 40) : [];

  return [
    {
      id: "organization",
      data: {
        "@context": "https://schema.org",
        "@type": "Organization",
        "@id": orgId,
        name: "220-km.com",
        alternateName: ["Open EMS", "Вирій EMS"],
        url: "https://220-km.com",
        email: "sales@220-km.com",
        logo: `${origin}/static/220-km-logo.svg`,
        areaServed: { "@type": "Country", name: "Ukraine" },
      },
    },
    {
      id: "breadcrumb",
      data: {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        itemListElement: [
          {
            "@type": "ListItem",
            position: 1,
            name: "Open EMS",
            item: origin,
          },
          {
            "@type": "ListItem",
            position: 2,
            name: t("commercialChargerPageTitle"),
            item: pageUrl,
          },
        ],
      },
    },
    {
      id: "collection",
      data: {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        name: t("commercialLandingSeoTitle"),
        description: t("commercialLandingSeoDescription"),
        url: pageUrl,
        inLanguage:
          locale === "uk" ? "uk-UA" : locale === "es" ? "es-ES" : "en-US",
        isPartOf: { "@id": orgId },
        mainEntity: {
          "@type": "ItemList",
          numberOfItems: list.length,
          itemListElement: list.map((p, i) => {
            const offer =
              p.price == null
                ? undefined
                : {
                    "@type": "Offer",
                    price: Number(p.price),
                    priceCurrency: (p.currency || "EUR").toUpperCase(),
                    availability: "https://schema.org/InStock",
                    url: p.link || pageUrl,
                  };
            return {
              "@type": "ListItem",
              position: i + 1,
              item: {
                "@type": "Product",
                name: p.title,
                sku: p.sku,
                brand: p.brand
                  ? { "@type": "Brand", name: p.brand }
                  : undefined,
                image: p.image
                  ? p.image.startsWith("http")
                    ? p.image
                    : `${origin}${p.image}`
                  : undefined,
                offers: offer,
              },
            };
          }),
        },
      },
    },
    {
      id: "faq",
      data: {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        mainEntity: commercialLandingFaqJsonLd(t),
      },
    },
  ];
}

/**
 * Buy commercial EV charger — EDS Chargers retail catalog with DC-hub filters.
 */
export default function BuyCommercialChargerPage({ t, locale }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [products, setProducts] = useState([]);
  const [facets, setFacets] = useState(null);
  const [notes, setNotes] = useState([]);

  const initialUrl = useMemo(() => readCatalogFromUrl(), []);
  const [sku, setSku] = useState(initialUrl.sku || "");
  const [brand, setBrand] = useState(
    () => initialUrl.brand || pickDefaultBrand(),
  );
  const [layout, setLayout] = useState(initialUrl.layout || "");
  const [power, setPower] = useState(initialUrl.power || "");
  const [cooling, setCooling] = useState(initialUrl.cooling || "");
  const [warranty, setWarranty] = useState(initialUrl.warranty || "");
  const [downtime, setDowntime] = useState(initialUrl.downtime || "");
  const [manager, setManager] = useState(initialUrl.manager || "");
  const [sort, setSort] = useState(initialUrl.sort || DEFAULT_SORT);
  const skuHydrated = useRef(false);
  const [displayCurrency, setDisplayCurrency] = useState(readStoredCurrency);
  const [eurUah, setEurUah] = useState(EUR_UAH_FALLBACK);
  const [usdUah, setUsdUah] = useState(USD_UAH_FALLBACK);
  const [fxMeta, setFxMeta] = useState(null);
  const [buyRequest, setBuyRequest] = useState(null);

  const pageJsonLd = useMemo(
    () => buildCommercialJsonLd(t, locale, products),
    [t, locale, products],
  );

  const originForOg =
    typeof window !== "undefined" && window.location?.origin
      ? window.location.origin
      : OPEN_EMS_SITE_URL;

  useOpenEmsSeo(t("commercialLandingSeoTitle"), locale, t, {
    variant: "landing",
    canonicalPath: CATALOG_PATH,
    description: t("commercialLandingSeoDescription"),
    ogTitle: t("commercialLandingSeoOgTitle"),
    ogImage: `${originForOg}/static/commercial-chargers-og.png`,
    keywords: t("commercialLandingSeoKeywords"),
    jsonLd: pageJsonLd,
  });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const res = await fetch(apiUrl("/api/commercial-chargers"), {
          cache: "no-store",
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (cancelled) return;
        setProducts(Array.isArray(data.products) ? data.products : []);
        setFacets(data.facets || null);
        setNotes(Array.isArray(data.notes) ? data.notes : []);
      } catch (e) {
        if (!cancelled) setError(t("commercialChargerLoadError"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [t]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const day = todayKyivIso();
      try {
        const [eurRes, usdRes] = await Promise.all([
          fetch(apiUrl(`/api/fx/eur-uah?date=${encodeURIComponent(day)}`), {
            cache: "no-store",
          }),
          fetch(apiUrl(`/api/fx/usd-uah?date=${encodeURIComponent(day)}`), {
            cache: "no-store",
          }),
        ]);
        const [eurData, usdData] = await Promise.all([
          eurRes.json(),
          usdRes.json(),
        ]);
        if (cancelled) return;
        const eurRate = eurData?.ok ? Number(eurData.rate) : NaN;
        const usdRate = usdData?.ok ? Number(usdData.rate) : NaN;
        if (Number.isFinite(eurRate) && eurRate > 0) setEurUah(eurRate);
        if (Number.isFinite(usdRate) && usdRate > 0) setUsdUah(usdRate);
        setFxMeta({
          date: eurData?.exchangedate || usdData?.exchangedate || day,
        });
      } catch {
        /* keep fallback rates */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const setCurrency = (next) => {
    setDisplayCurrency(next);
    writeStoredCurrency(next);
  };

  useEffect(() => {
    writeCatalogToUrl({
      sku,
      brand,
      layout,
      power,
      cooling,
      warranty,
      downtime,
      manager,
      sort,
    });
  }, [sku, brand, layout, power, cooling, warranty, downtime, manager, sort]);

  useEffect(() => {
    if (layout === "station_dcdc" && brand && brand !== "infi") setBrand("");
  }, [layout, brand]);

  useEffect(() => {
    if (skuHydrated.current || !sku || !products.length) return;
    const p = products.find((x) => x.sku === sku);
    if (!p) return;
    skuHydrated.current = true;
    if (!brand && brandFilterValue(p)) setBrand(brandFilterValue(p));
    if (!layout) setLayout(productLayout(p));
    if (!power && p.power_bucket) setPower(p.power_bucket);
    if (!cooling && p.cooling) setCooling(p.cooling);
    if (!warranty && p.warranty_years) setWarranty(String(p.warranty_years));
    if (!downtime && p.warranty_downtime) setDowntime(p.warranty_downtime);
    if (!manager && managerFilterValue(p)) setManager(managerFilterValue(p));
  }, [
    products,
    sku,
    brand,
    layout,
    power,
    cooling,
    warranty,
    downtime,
    manager,
  ]);

  useEffect(() => {
    if (!sku || !products.length) return;
    const p = products.find((x) => x.sku === sku);
    if (!p) {
      setSku("");
      return;
    }
    if (brand && brandFilterValue(p) !== brand) setSku("");
    else if (layout && productLayout(p) !== layout) setSku("");
    else if (power && !meetsPowerFilter(p, power)) setSku("");
    else if (cooling && p.cooling !== cooling) setSku("");
    else if (warranty && String(p.warranty_years) !== warranty) setSku("");
    else if (downtime && p.warranty_downtime !== downtime) setSku("");
    else if (manager && managerFilterValue(p) !== manager) setSku("");
  }, [
    sku,
    brand,
    layout,
    power,
    cooling,
    warranty,
    downtime,
    manager,
    products,
  ]);

  const filtered = useMemo(() => {
    let list = products.slice();
    if (brand) list = list.filter((p) => brandFilterValue(p) === brand);
    if (layout) list = list.filter((p) => productLayout(p) === layout);
    if (power) list = list.filter((p) => meetsPowerFilter(p, power));
    if (cooling) list = list.filter((p) => p.cooling === cooling);
    if (warranty)
      list = list.filter((p) => String(p.warranty_years) === warranty);
    if (downtime) list = list.filter((p) => p.warranty_downtime === downtime);
    if (manager) list = list.filter((p) => managerFilterValue(p) === manager);

    list.sort((a, b) => {
      if (sku) {
        if (a.sku === sku && b.sku !== sku) return -1;
        if (b.sku === sku && a.sku !== sku) return 1;
      }
      const pa = toDisplayAmount(
        a.price,
        a.currency,
        displayCurrency,
        eurUah,
        usdUah,
      );
      const pb = toDisplayAmount(
        b.price,
        b.currency,
        displayCurrency,
        eurUah,
        usdUah,
      );
      const na = pa == null ? Number.POSITIVE_INFINITY : pa;
      const nb = pb == null ? Number.POSITIVE_INFINITY : pb;
      if (sort === "price-desc") return nb - na;
      if (sort === "power-desc") return (b.power_kw || 0) - (a.power_kw || 0);
      return na - nb;
    });
    return list;
  }, [
    products,
    brand,
    layout,
    power,
    cooling,
    warranty,
    downtime,
    manager,
    sort,
    sku,
    displayCurrency,
    eurUah,
    usdUah,
  ]);

  useEffect(() => {
    if (!sku || loading) return;
    const el = findSkuCard(sku);
    if (!el) return;
    el.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [sku, loading, filtered.length]);

  const clearFilters = () => {
    setSku("");
    setBrand("");
    setLayout("");
    setPower("");
    setCooling("");
    setWarranty("");
    setDowntime("");
    setManager("");
  };

  const hasFilters = Boolean(
    sku ||
    brand ||
    layout ||
    power ||
    cooling ||
    warranty ||
    downtime ||
    manager,
  );

  const openBuyRequest = (p) => {
    setSku(p.sku);
    setBuyRequest({
      catalog: "commercial",
      title: p.title,
      sku: p.sku,
      price:
        p.price == null
          ? t("commercialChargerPriceOnRequest")
          : fmtMoney(p.price, p.currency || "EUR", locale),
      pageUrl: productQuotePageUrl(p),
      productUrl: p.link,
    });
  };

  const openGenericQuote = (title) => {
    const pageUrl =
      typeof window !== "undefined"
        ? `${window.location.origin}${CATALOG_PATH}`
        : CATALOG_PATH;
    // Ignore click/keyboard SyntheticEvent if the handler is passed to onClick directly.
    const safeTitle = typeof title === "string" && title ? title : null;
    setBuyRequest({
      catalog: "commercial",
      title: safeTitle || t("commercialChargerPageTitle"),
      sku: null,
      price: t("commercialChargerPriceOnRequest"),
      pageUrl,
      productUrl: null,
    });
  };

  const browseCatalog = () => {
    const el = document.getElementById("catalog");
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <div className="home-charger-page">
      <div className="home-charger-page__inner">
        <ChargerCatalogSegmentBar t={t} active="business" />
        <CommercialHero
          t={t}
          onBrowseCatalog={browseCatalog}
          onRequestQuote={() => openGenericQuote()}
        />

        <section
          id="catalog"
          className="home-charger-filters"
          aria-label={t("commercialChargerFiltersAria")}
        >
          <div className="home-charger-filters__top">
            <button
              type="button"
              className="home-charger-clear home-charger-clear--top"
              onClick={clearFilters}
              disabled={!hasFilters}
            >
              {t("commercialChargerClearFilters")}
            </button>
          </div>
          <div className="home-charger-filters__row">
            <span className="home-charger-filters__label">
              {t("commercialChargerFilterBrand")}
            </span>
            <div className="home-charger-chips">
              <Chip active={!brand} onClick={() => setBrand("")}>
                {t("commercialChargerFilterAny")}
              </Chip>
              {Array.from(
                new Set(
                  facets?.brands?.length
                    ? facets.brands
                        .map((label) => brandFilterValue({ brand: label }))
                        .filter(Boolean)
                    : BRAND_IDS,
                ),
              ).map((id) => (
                <Chip
                  key={id}
                  active={brand === id}
                  disabled={layout === "station_dcdc" && id !== "infi"}
                  onClick={() => setBrand(brand === id ? "" : id)}
                >
                  {brandLabel(id)}
                </Chip>
              ))}
            </div>
          </div>
          <div className="home-charger-filters__row">
            <span className="home-charger-filters__label">
              {t("commercialChargerFilterLayout")}
            </span>
            <div className="home-charger-chips">
              <Chip active={!layout} onClick={() => setLayout("")}>
                {t("commercialChargerFilterAny")}
              </Chip>
              {LAYOUT_IDS.map((id) => (
                <Chip
                  key={id}
                  active={layout === id}
                  onClick={() => setLayout(layout === id ? "" : id)}
                >
                  {layoutLabel(id, t)}
                </Chip>
              ))}
            </div>
          </div>
          <div className="home-charger-filters__row">
            <span className="home-charger-filters__label">
              {t("commercialChargerFilterPower")}
            </span>
            <div className="home-charger-chips">
              <Chip active={!power} onClick={() => setPower("")}>
                {t("commercialChargerFilterAny")}
              </Chip>
              {POWER_FILTERS.map((item) => (
                <Chip
                  key={item.id}
                  active={power === item.id}
                  onClick={() => setPower(power === item.id ? "" : item.id)}
                >
                  {powerFilterLabel(item.id, t)}
                </Chip>
              ))}
            </div>
          </div>

          {(facets?.cooling || []).length > 0 ? (
            <div className="home-charger-filters__row">
              <span className="home-charger-filters__label">
                {t("commercialChargerFilterCooling")}
              </span>
              <div className="home-charger-chips">
                <Chip active={!cooling} onClick={() => setCooling("")}>
                  {t("commercialChargerFilterAny")}
                </Chip>
                {facets.cooling.map((c) => (
                  <Chip
                    key={c}
                    active={cooling === c}
                    onClick={() => setCooling(cooling === c ? "" : c)}
                  >
                    {coolingLabel(c, t)}
                  </Chip>
                ))}
              </div>
            </div>
          ) : null}

          <div className="home-charger-filters__row">
            <span className="home-charger-filters__label">
              {t("commercialChargerFilterWarranty")}
            </span>
            <div className="home-charger-chips">
              <Chip active={!warranty} onClick={() => setWarranty("")}>
                {t("commercialChargerFilterAny")}
              </Chip>
              {WARRANTY_YEARS.map((y) => (
                <Chip
                  key={y}
                  active={warranty === y}
                  onClick={() => setWarranty(warranty === y ? "" : y)}
                >
                  {warrantyYearsLabel(y, t)}
                </Chip>
              ))}
            </div>
          </div>

          <div className="home-charger-filters__row">
            <span className="home-charger-filters__label">
              {t("commercialChargerFilterDowntime")}
            </span>
            <p className="home-charger-filters__hint">
              {t("commercialChargerDowntimeHint")}
            </p>
            <div className="home-charger-chips">
              <Chip active={!downtime} onClick={() => setDowntime("")}>
                {t("commercialChargerFilterAny")}
              </Chip>
              {DOWNTIME_IDS.map((d) => (
                <Chip
                  key={d}
                  active={downtime === d}
                  onClick={() => setDowntime(downtime === d ? "" : d)}
                >
                  {downtimeLabel(d, t)}
                </Chip>
              ))}
            </div>
          </div>

          <div className="home-charger-filters__row">
            <span className="home-charger-filters__label">
              {t("commercialChargerFilterManager")}
            </span>
            <div className="home-charger-chips">
              <Chip active={!manager} onClick={() => setManager("")}>
                {t("commercialChargerFilterAny")}
              </Chip>
              {MANAGER_IDS.map((m) => (
                <Chip
                  key={m}
                  active={manager === m}
                  onClick={() => setManager(manager === m ? "" : m)}
                >
                  {managerLabel(m, t)}
                </Chip>
              ))}
            </div>
          </div>

          <div className="home-charger-filters__toolbar">
            <label className="home-charger-sort">
              <span>{t("commercialChargerSort")}</span>
              <select value={sort} onChange={(e) => setSort(e.target.value)}>
                <option value="price-asc">
                  {t("commercialChargerSortPriceAsc")}
                </option>
                <option value="price-desc">
                  {t("commercialChargerSortPriceDesc")}
                </option>
                <option value="power-desc">
                  {t("commercialChargerSortPowerDesc")}
                </option>
              </select>
            </label>
            <div
              className="home-charger-currency"
              role="group"
              aria-label={t("commercialChargerCurrency")}
            >
              <Chip
                active={displayCurrency === "EUR"}
                onClick={() => setCurrency("EUR")}
              >
                EUR
              </Chip>
              <Chip
                active={displayCurrency === "USD"}
                onClick={() => setCurrency("USD")}
              >
                USD
              </Chip>
              <Chip
                active={displayCurrency === "UAH"}
                onClick={() => setCurrency("UAH")}
              >
                UAH
              </Chip>
            </div>
            <p className="home-charger-count">
              {t("commercialChargerResultCount", { count: filtered.length })}
            </p>
          </div>
        </section>

        {loading ? (
          <p className="home-charger-muted">{t("commercialChargerLoading")}</p>
        ) : null}
        {error ? <p className="home-charger-error">{error}</p> : null}

        {!loading && !error && filtered.length === 0 ? (
          <p className="home-charger-muted">{t("commercialChargerEmpty")}</p>
        ) : null}

        <div className="home-charger-grid">
          {filtered.map((p) => (
            <article
              key={p.id}
              data-charger-sku={p.sku}
              className={`home-charger-card${p.sku === sku ? " home-charger-card--selected" : ""}`}
            >
              <div
                className={`home-charger-card__media${
                  p.form === "split" || p.form === "dispenser"
                    ? " home-charger-card__media--scene"
                    : ""
                }`}
              >
                {p.image ? (
                  <img src={p.image} alt="" loading="lazy" decoding="async" />
                ) : (
                  <div className="home-charger-card__placeholder" aria-hidden />
                )}
              </div>
              <div className="home-charger-card__body">
                <h2 className="home-charger-card__title">{p.title}</h2>
                <ul className="home-charger-card__meta">
                  {p.brand ? (
                    <li>
                      {t("commercialChargerMetaBrand")}:{" "}
                      <strong>{p.brand}</strong>
                    </li>
                  ) : null}
                  {p.power_kw != null ? (
                    <li>
                      {t("commercialChargerMetaPower")}:{" "}
                      <strong>{p.power_kw} kW</strong>
                    </li>
                  ) : null}
                  {p.series && p.series !== "UGV" ? (
                    <li>
                      {t("commercialChargerMetaSeries")}:{" "}
                      <strong>{seriesLabel(p.series, t)}</strong>
                    </li>
                  ) : null}
                  {p.ports ? (
                    <li>
                      {t("commercialChargerMetaPorts")}:{" "}
                      <strong>{portsLabel(p.ports, t)}</strong>
                    </li>
                  ) : p.config ? (
                    <li>
                      {t("commercialChargerMetaConfig")}:{" "}
                      <strong>{p.config}</strong>
                    </li>
                  ) : null}
                  {p.connectors?.length ? (
                    <li>
                      {t("commercialChargerMetaConnector")}:{" "}
                      <strong>{p.connectors.join(" / ")}</strong>
                    </li>
                  ) : null}
                  {p.cooling ? (
                    <li>
                      {t("commercialChargerMetaCooling")}:{" "}
                      <strong>{coolingLabel(p.cooling, t)}</strong>
                    </li>
                  ) : null}
                  {p.warranty_years ? (
                    <li>
                      {t("commercialChargerMetaWarranty")}:{" "}
                      <strong>{warrantyYearsLabel(p.warranty_years, t)}</strong>
                    </li>
                  ) : null}
                  {p.warranty_downtime ? (
                    <li title={t("commercialChargerDowntimeHint")}>
                      {t("commercialChargerMetaDowntime")}:{" "}
                      <strong>{downtimeLabel(p.warranty_downtime, t)}</strong>
                    </li>
                  ) : null}
                  {p.dedicated_manager != null ? (
                    <li>
                      {t("commercialChargerMetaManager")}:{" "}
                      <strong>{managerLabel(managerFilterValue(p), t)}</strong>
                    </li>
                  ) : null}
                  {p.lead_time ? (
                    <li>
                      {t("commercialChargerMetaLeadTime")}:{" "}
                      <strong>{leadTimeLabel(p.lead_time, t)}</strong>
                    </li>
                  ) : null}
                </ul>
                <div className="home-charger-card__footer">
                  <p className="home-charger-card__price">
                    {p.price == null
                      ? t("commercialChargerPriceOnRequest")
                      : fmtMoney(
                          toDisplayAmount(
                            p.price,
                            p.currency,
                            displayCurrency,
                            eurUah,
                            usdUah,
                          ),
                          displayCurrency,
                          locale,
                        )}
                  </p>
                  <button
                    type="button"
                    className="home-charger-card__buy"
                    onClick={() => openBuyRequest(p)}
                  >
                    {t("commercialChargerBuy")}
                  </button>
                </div>
              </div>
            </article>
          ))}
        </div>

        {displayCurrency !== "EUR" ? (
          <p className="home-charger-fx">
            {t("commercialChargerFxNote", {
              eur: new Intl.NumberFormat(locale === "uk" ? "uk-UA" : "en-US", {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              }).format(eurUah),
              usd: new Intl.NumberFormat(locale === "uk" ? "uk-UA" : "en-US", {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              }).format(usdUah),
              date: fxMeta?.date || todayKyivIso(),
            })}
          </p>
        ) : null}
        {notes.length ? (
          <ul className="home-charger-notes">
            {notes.map((n) => (
              <li key={n}>{n.replace(/^\*+/, "").trim()}</li>
            ))}
          </ul>
        ) : (
          <p className="home-charger-fx">{t("commercialChargerVatNote")}</p>
        )}

        <CommercialMarketingSections
          t={t}
          onRequestQuote={() => openGenericQuote()}
          onPartnerRequest={() =>
            openGenericQuote(t("commercialLandingPartnerTitle"))
          }
        />
      </div>

      {buyRequest ? (
        <ChargerBuyRequestModal
          t={t}
          product={buyRequest}
          onClose={() => setBuyRequest(null)}
        />
      ) : null}
    </div>
  );
}
