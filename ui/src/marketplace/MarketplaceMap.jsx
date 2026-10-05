import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as maptilersdk from "@maptiler/sdk";
import maplibregl from "maplibre-gl";
import "@maptiler/sdk/dist/maptiler-sdk.css";
import { getClientId } from "./clientId";
import {
  formatDistanceMeters,
  buildGoogleMapsPointUrl,
} from "./messengerLinks";
import {
  createHeatmapZoomPayment,
  createHeatmapZoomTestPayment,
  createMarketplaceInfoPayment,
  createMarketplaceTestPayment,
  fetchMarketplaceLocations,
  fetchMarketplacePaymentStatus,
  fetchPendingMarketplaceLocations,
  getStoredMarketplacePaymentId,
  isMarketplaceApiConfigured,
  isMarketplaceLocalTestPaymentEnabled,
  resolveMarketplaceAssetUrl,
  storeMarketplaceUnlockedPayment,
} from "./marketplaceApi";
import {
  isHeatmapZoomUnlocked,
  isMarketplaceUiLocalDev,
  storeHeatmapZoomUnlock,
  storeHeatmapZoomUnlockLocalDev,
} from "./marketplaceHeatmapAccess";
import { useEvua80KwStations } from "./useEvua80KwStations";
import { useGovmapHeatmapPoints } from "./useGovmapHeatmapPoints";
import { useDriverGpsHeatmapPoints } from "./useDriverGpsHeatmapPoints";
import {
  aggregateHeatmapPoints,
  buildHeatmapWeightedPoints,
  HEATMAP_INTENSITY_SCALE,
  HEATMAP_LAYER_OPACITY,
  precisionForZoom,
} from "./marketplaceHeatmapPoints";
import { downloadContractPhotosAsPdf } from "./marketplaceContractPdf";
import {
  formatLandlordLegalForm,
  formatMinRentYears,
} from "./marketplaceLease";
import {
  formatKwLabel,
  markerFontPxForKw,
  markerSizePxForKw,
} from "./marketplaceKw";
import { buildMarketplacePayRedirectBase } from "./marketplacePayRedirect";
import { infoPaymentAmountUah } from "./marketplacePaymentAmounts";
import MarketplaceModal from "./MarketplaceModal";
import styles from "./MarketplaceMap.module.css";

const MAPTILER_API_KEY = "1Lk2s9HJjoiXBR1oqw5a";
// Must match the installed maplibre-gl. prestart/prebuild copy the package worker into public/.
// The query string busts a cached MapLibre 4.7 worker, which rejects GeoJSON and hides pins.
const MAPLIBRE_WORKER_URL = `${process.env.PUBLIC_URL || ""}/maplibre-gl-csp-worker.js?v=5.24.0`;
const UKRAINE_CENTER = [31.223, 49.454];
const DEFAULT_ZOOM = 6;
/** Unpaid zoom stops once 100 px on screen covers 5 km or less. After 44 UAH the heatmap stays on every scale. */
const HEATMAP_SHOW_SPAN_PX = 100;
const HEATMAP_SHOW_MAX_METERS = 5000;
const HEATMAP_SOURCE_ID = "b2b-marketplace-looking-heatmap";
const HEATMAP_LAYER_ID = "b2b-marketplace-looking-heatmap-layer";
const HEATMAP_SCALE_BAR_MAX_PX = 120;
/** Heatmap overlay and zoom-in stay locked until today's 44 UAH payment is stored. */
const HEATMAP_PAY_AMOUNT_UAH = 44;

if (typeof maplibregl.setWorkerUrl === "function") {
  maplibregl.setWorkerUrl(MAPLIBRE_WORKER_URL);
}

/** Web-mercator zoom where `px` screen pixels span `meters` at `latDeg`. */
function zoomForGroundSpan(latDeg, meters, px) {
  const lat = (latDeg * Math.PI) / 180;
  const mpp = meters / px;
  const cos = Math.cos(lat);
  if (!Number.isFinite(cos) || cos <= 0.01 || mpp <= 0) return 18;
  return Math.log2((156543.03392 * cos) / mpp);
}

function heatmapLockMaxZoom(map) {
  const lat = map.getCenter?.()?.lat ?? UKRAINE_CENTER[1];
  const zoom = zoomForGroundSpan(
    lat,
    HEATMAP_SHOW_MAX_METERS,
    HEATMAP_SHOW_SPAN_PX,
  );
  return Math.min(21, Math.max(DEFAULT_ZOOM, zoom));
}

/** True when the map is zoomed in closer than a 5 km scale. */
function isZoomedCloserThanHeatmapScale(map) {
  try {
    const canvas = map.getCanvas();
    const x = canvas.clientWidth / 2;
    const y = canvas.clientHeight / 2;
    const left = map.unproject([x, y]);
    const right = map.unproject([x + HEATMAP_SHOW_SPAN_PX, y]);
    if (!left || typeof left.distanceTo !== "function") return false;
    return left.distanceTo(right) <= HEATMAP_SHOW_MAX_METERS;
  } catch {
    return false;
  }
}

function resolveMapLanguage(locale) {
  const lang = String(locale || "uk").toLowerCase();
  if (lang.startsWith("en")) return maptilersdk.Language.ENGLISH;
  if (lang.startsWith("es")) return maptilersdk.Language.SPANISH;
  if (lang.startsWith("de")) return maptilersdk.Language.GERMAN;
  if (lang.startsWith("fr")) return maptilersdk.Language.FRENCH;
  if (lang.startsWith("pl")) return maptilersdk.Language.POLISH;
  if (lang.startsWith("nl")) return maptilersdk.Language.DUTCH;
  if (lang.startsWith("cs")) return maptilersdk.Language.CZECH;
  if (lang.startsWith("bg")) return maptilersdk.Language.BULGARIAN;
  return maptilersdk.Language.UKRAINIAN;
}

function flattenLocations(items) {
  const points = [];
  (items || []).forEach((item) => {
    const requestType = item.request_type === "LOOKING" ? "LOOKING" : "PROPOSE";
    const pending = item.status === "PENDING";
    const hasContract =
      item.distribution_contract === true
        ? 1
        : item.distribution_contract === false
          ? 0
          : -1;
    (item.locations || []).forEach((loc, index) => {
      points.push({
        id: `${item.id}-${index}`,
        itemId: String(item.id),
        lat: loc.lat,
        lng: loc.lng,
        label: loc.label,
        hasContract,
        kw: item.kw_available,
        requestType,
        pending,
      });
    });
  });
  return points;
}

function markerClassForPoint(point, styles) {
  if (point.pending) return styles.mapMarkerPending;
  return point.requestType === "LOOKING"
    ? styles.mapMarkerLooking
    : styles.mapMarkerPropose;
}

function createMarketplaceMarkerElement(point, styles) {
  const el = document.createElement("button");
  el.type = "button";
  el.className = [styles.mapMarker, markerClassForPoint(point, styles)].join(
    " ",
  );
  el.textContent = formatKwLabel(point.kw);
  const size = markerSizePxForKw(point.kw);
  el.style.setProperty("--mp-marker-size", `${size}px`);
  el.style.setProperty("--mp-marker-font", `${markerFontPxForKw(point.kw)}px`);
  el.style.zIndex = String(Math.max(1, 160 - size));
  return el;
}

function removeMarketplaceMarkers(markersRef) {
  markersRef.current.forEach((marker) => marker.remove());
  markersRef.current = [];
}

function syncMarketplaceMarkers(map, points, onSelect, markersRef, styles) {
  removeMarketplaceMarkers(markersRef);
  if (!map || !points?.length) return;

  points.forEach((point) => {
    const el = createMarketplaceMarkerElement(point, styles);
    el.addEventListener("click", (event) => {
      event.stopPropagation();
      onSelect(point);
    });
    const marker = new maptilersdk.Marker({ element: el, anchor: "center" })
      .setLngLat([point.lng, point.lat])
      .addTo(map);
    markersRef.current.push(marker);
  });
}

function heatmapPointsToGeoJson(regions) {
  return {
    type: "FeatureCollection",
    features: (regions || []).map((region) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [region.lng, region.lat] },
      properties: { weight: region.weight },
    })),
  };
}

function heatmapSyncKey(zoom, pointCount) {
  return `${precisionForZoom(zoom)}:${pointCount}`;
}

const HEATMAP_PAINT = {
  "heatmap-weight": [
    "interpolate",
    ["linear"],
    ["get", "weight"],
    0,
    0,
    0.4,
    0.5,
    0.75,
    0.75,
    1,
    1,
  ],
  "heatmap-intensity": [
    "interpolate",
    ["linear"],
    ["zoom"],
    4,
    0.45 * HEATMAP_INTENSITY_SCALE,
    6,
    0.65 * HEATMAP_INTENSITY_SCALE,
    9,
    1.2 * HEATMAP_INTENSITY_SCALE,
    11,
    1.9 * HEATMAP_INTENSITY_SCALE,
    13,
    2.6 * HEATMAP_INTENSITY_SCALE,
  ],
  "heatmap-color": [
    "interpolate",
    ["linear"],
    ["heatmap-density"],
    0,
    "rgba(33, 102, 172, 0)",
    0.08,
    "rgba(103, 169, 207, 0.5)",
    0.18,
    "rgb(140, 211, 175)",
    0.3,
    "rgb(253, 219, 99)",
    0.42,
    "rgb(244, 109, 67)",
    0.52,
    "rgb(215, 25, 28)",
  ],
  "heatmap-radius": [
    "interpolate",
    ["linear"],
    ["zoom"],
    4,
    12,
    6,
    18,
    9,
    28,
    11,
    38,
    13,
    52,
  ],
  "heatmap-opacity": HEATMAP_LAYER_OPACITY,
};

function removeHeatmapLayer(map) {
  if (!map?.getStyle?.()) return;
  try {
    if (map.getLayer(HEATMAP_LAYER_ID)) map.removeLayer(HEATMAP_LAYER_ID);
    if (map.getSource(HEATMAP_SOURCE_ID)) map.removeSource(HEATMAP_SOURCE_ID);
  } catch {
    // Style may be reloading while the map is torn down.
  }
}

function isMapHeatmapReady(map) {
  return Boolean(map && typeof map.loaded === "function" && map.loaded());
}

function upsertHeatmapLayer(map, regions) {
  if (!regions?.length) {
    removeHeatmapLayer(map);
    return;
  }
  if (!isMapHeatmapReady(map)) return;

  const data = heatmapPointsToGeoJson(regions);
  const existingSource = map.getSource(HEATMAP_SOURCE_ID);
  if (existingSource && typeof existingSource.setData === "function") {
    existingSource.setData(data);
    return;
  }

  removeHeatmapLayer(map);
  map.addSource(HEATMAP_SOURCE_ID, { type: "geojson", data });
  const heatmapLayer = {
    id: HEATMAP_LAYER_ID,
    type: "heatmap",
    source: HEATMAP_SOURCE_ID,
    paint: HEATMAP_PAINT,
  };
  try {
    map.addLayer({ ...heatmapLayer, slot: "top" });
  } catch {
    if (!map.getLayer(HEATMAP_LAYER_ID)) map.addLayer(heatmapLayer);
  }
}

function syncHeatmapLayerData(
  map,
  heatmapPoints,
  zoom,
  visible = false,
  lastSyncKeyRef = null,
) {
  const regions = aggregateHeatmapPoints(heatmapPoints, precisionForZoom(zoom));
  if (!isMapHeatmapReady(map)) {
    return regions;
  }

  if (!visible || !regions.length) {
    removeHeatmapLayer(map);
    if (lastSyncKeyRef) lastSyncKeyRef.current = "";
    return regions;
  }

  const syncKey = heatmapSyncKey(zoom, heatmapPoints.length);
  if (lastSyncKeyRef?.current === syncKey && map.getLayer(HEATMAP_LAYER_ID)) {
    return regions;
  }

  try {
    upsertHeatmapLayer(map, regions);
    if (lastSyncKeyRef) lastSyncKeyRef.current = syncKey;
  } catch {
    removeHeatmapLayer(map);
    if (lastSyncKeyRef) lastSyncKeyRef.current = "";
  }
  return regions;
}

function formatContract(value, t) {
  if (value === true) return t("marketplaceLeadFormYes");
  if (value === false) return t("marketplaceLeadFormNo");
  return "—";
}

function marketplaceRelativeTimeLocale(language) {
  const lang = String(language || "").toLowerCase();
  if (lang.startsWith("uk") || lang.startsWith("ua")) return "uk";
  if (lang.startsWith("es")) return "es";
  if (lang.startsWith("ru")) return "ru";
  return "en";
}

function formatMarketplacePublicationRelative(isoDate, language) {
  if (!isoDate) return "";
  const date = new Date(isoDate);
  if (Number.isNaN(date.getTime())) return "";

  const diffMs = Date.now() - date.getTime();
  if (diffMs < 0) return "";

  const rtf = new Intl.RelativeTimeFormat(
    marketplaceRelativeTimeLocale(language),
    { numeric: "always" },
  );
  const diffMinutes = Math.floor(diffMs / (1000 * 60));
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays >= 365) {
    return rtf.format(-Math.floor(diffDays / 365), "year");
  }
  if (diffDays >= 30) {
    return rtf.format(-Math.floor(diffDays / 30), "month");
  }
  if (diffDays >= 1) {
    return rtf.format(-diffDays, "day");
  }
  if (diffHours >= 1) {
    return rtf.format(-diffHours, "hour");
  }
  return rtf.format(-Math.max(1, diffMinutes), "minute");
}

function MarketplaceDetailsBody({
  item,
  t,
  variant = "full",
  language = "ua",
}) {
  const photoSections =
    variant === "map"
      ? [
          {
            key: "parking",
            photos: item.parking_photos,
            label: t("marketplaceMapParkingPhotos"),
          },
        ]
      : [
          {
            key: "parking",
            photos: item.parking_photos,
            label: t("marketplaceLeadFormParkingPhotosLabel"),
          },
          {
            key: "connection",
            photos: item.connection_point_photos,
            label: t("marketplaceLeadFormConnectionPhotosLabel"),
          },
          {
            key: "distribution",
            photos: item.distribution_contract_photos,
            label: t("marketplaceDistributionContractPhotosLabel"),
          },
        ];
  const visiblePhotoSections = photoSections.filter(
    (section) => section.photos?.length > 0,
  );
  const publicationRelative = formatMarketplacePublicationRelative(
    item.published_on || item.created_on,
    language,
  );

  const photoBlock =
    visiblePhotoSections.length > 0 ? (
      <div className={styles.photoGroups}>
        {visiblePhotoSections.map((section) => (
          <div key={section.key} className={styles.photoGroup}>
            <span className={styles.photoGroupLabel}>{section.label}</span>
            <div className={styles.photoRow}>
              {section.photos.map((url) => (
                <a
                  key={url}
                  href={resolveMarketplaceAssetUrl(url)}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <img
                    src={resolveMarketplaceAssetUrl(url)}
                    alt=""
                    className={styles.photoThumb}
                  />
                </a>
              ))}
            </div>
          </div>
        ))}
      </div>
    ) : null;

  return (
    <>
      {/* Photos first so investors see the site before paying for contacts. */}
      {photoBlock}

      <div className={styles.detailBadges}>
        <span className={styles.kwBadge}>
          {formatKwLabel(item.kw_available)}
        </span>
        {item.distribution_contract != null ? (
          <span
            className={`${styles.contractBadge} ${
              item.distribution_contract
                ? styles.contractBadgeYes
                : styles.contractBadgeNo
            }`}
          >
            {t("marketplaceLeadFormDistributionLabel")}:{" "}
            {formatContract(item.distribution_contract, t)}
          </span>
        ) : null}
        {item.distance_meters != null ? (
          <span className={styles.distanceBadge}>
            {t("marketplaceLeadFormDistanceLabel")}:{" "}
            {formatDistanceMeters(item.distance_meters, t)}
          </span>
        ) : null}
        {item.price_per_kwh_extra != null ? (
          <span className={styles.distanceBadge}>
            {t("marketplaceLeadFormPriceKwhExtraLabel")}:{" "}
            {Number(item.price_per_kwh_extra).toFixed(1)} ₴
          </span>
        ) : null}
        {item.monthly_price_parking != null ? (
          <span className={styles.distanceBadge}>
            {t("marketplaceLeadFormMonthlyParkingLabel")}:{" "}
            {item.monthly_price_parking} ₴
          </span>
        ) : null}
        {item.min_rent_years ? (
          <span className={styles.distanceBadge}>
            {t("marketplaceLeadFormMinRentLabel")}:{" "}
            {formatMinRentYears(item.min_rent_years, t)}
          </span>
        ) : null}
        {item.restroom_coffee_nearby != null ? (
          <span className={styles.distanceBadge}>
            {t("marketplaceLeadFormRestroomCoffeeLabel")}:{" "}
            {formatContract(item.restroom_coffee_nearby, t)}
          </span>
        ) : null}
        {item.more_stations_possible != null ? (
          <span className={styles.distanceBadge}>
            {t("marketplaceLeadFormMoreStationsLabel")}:{" "}
            {formatContract(item.more_stations_possible, t)}
          </span>
        ) : null}
        {item.parking_spaces_now != null ? (
          <span className={styles.distanceBadge}>
            {t("marketplaceLeadFormParkingSpacesNowLabel")}:{" "}
            {item.parking_spaces_now}
          </span>
        ) : null}
        {item.parking_spaces_future != null ? (
          <span className={styles.distanceBadge}>
            {t("marketplaceLeadFormParkingSpacesFutureLabel")}:{" "}
            {item.parking_spaces_future}
          </span>
        ) : null}
        {item.landlord_legal_form ? (
          <span className={styles.distanceBadge}>
            {t("marketplaceLeadFormLandlordLabel")}:{" "}
            {formatLandlordLegalForm(item.landlord_legal_form, t)}
          </span>
        ) : null}
      </div>

      {publicationRelative ? (
        <p className={styles.publicationDate}>
          {t("marketplacePublishedOn", { timeAgo: publicationRelative })}
        </p>
      ) : null}

      <ul className={styles.locationList}>
        {(item.locations || []).map((loc, index) => (
          <li key={`${item.id}-loc-${index}`} className={styles.locationItem}>
            <a
              className={styles.locationItemLink}
              href={buildGoogleMapsPointUrl(loc.lat, loc.lng)}
              target="_blank"
              rel="noopener noreferrer"
            >
              {index + 1}. {loc.label}
            </a>
          </li>
        ))}
      </ul>
    </>
  );
}

function OwnerInfoBody({ ownerInfo, t }) {
  if (!ownerInfo) return null;

  const contractPhotos = (ownerInfo.distribution_contract_photos || []).filter(
    Boolean,
  );

  return (
    <div className={styles.ownerInfoBody}>
      <div className={styles.ownerInfoRow}>
        <span className={styles.ownerInfoLabel}>
          {t("marketplaceOwnerName")}
        </span>
        <span className={styles.ownerInfoValue}>{ownerInfo.name}</span>
      </div>
      <div className={styles.ownerInfoRow}>
        <span className={styles.ownerInfoLabel}>
          {t("marketplaceOwnerPhone")}
        </span>
        <a className={styles.ownerInfoPhone} href={`tel:${ownerInfo.phone}`}>
          {ownerInfo.phone}
        </a>
      </div>
      {contractPhotos.length > 0 ? (
        <div className={styles.photoGroup}>
          <span className={styles.photoGroupLabel}>
            {t("marketplaceDistributionContractPhotosLabel")}
          </span>
          <div className={styles.photoRow}>
            {contractPhotos.map((url) => (
              <a
                key={url}
                href={resolveMarketplaceAssetUrl(url)}
                target="_blank"
                rel="noopener noreferrer"
              >
                <img
                  src={resolveMarketplaceAssetUrl(url)}
                  alt=""
                  className={styles.photoThumbLarge}
                />
              </a>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

const PAYMENT_SUCCESS = "SUCCESS";
const PAYMENT_FAILED = new Set(["FAILURE", "EXPIRED", "REVERSED"]);

export default function MarketplaceMap({
  t,
  locale = "uk",
  requestType = "PROPOSE",
  hideHeader = false,
  showLookingHeatmap = true,
  showLookingMarkers = true,
  loadEvuaHeatmap = false,
  paymentReturnId = "",
  paymentReturnLocationId = "",
  onPaymentReturnHandled,
  heatmapPaymentReturnId = "",
  onHeatmapPaymentReturnHandled,
}) {
  const mapContainerRef = useRef(null);
  const mapRef = useRef(null);
  const htmlMarkersRef = useRef([]);
  const itemsRef = useRef([]);
  const pointsRef = useRef([]);
  const heatmapRegionsRef = useRef([]);
  const heatmapPointsRef = useRef([]);
  const heatmapSyncGenerationRef = useRef(0);
  const lastHeatmapSyncKeyRef = useRef("");
  const lastAllowedZoomRef = useRef(DEFAULT_ZOOM);
  const restoringZoomRef = useRef(false);
  const heatmapZoomUnlockedRef = useRef(isHeatmapZoomUnlocked());
  const [mapReady, setMapReady] = useState(false);
  const [items, setItems] = useState([]);
  const [lookingItems, setLookingItems] = useState([]);
  const [pendingItems, setPendingItems] = useState([]);
  const heatmapEnabled = showLookingHeatmap && loadEvuaHeatmap;
  const [heatmapZoomUnlocked, setHeatmapZoomUnlocked] = useState(() =>
    isHeatmapZoomUnlocked(),
  );
  const heatmapDataEnabled = heatmapEnabled && heatmapZoomUnlocked;
  const { stations: evuaStations } = useEvua80KwStations(heatmapDataEnabled);
  const { points: govmapPoints } = useGovmapHeatmapPoints(heatmapDataEnabled);
  const { points: driverGpsPoints } =
    useDriverGpsHeatmapPoints(heatmapDataEnabled);
  const heatmapPoints = useMemo(
    () =>
      buildHeatmapWeightedPoints(evuaStations, govmapPoints, driverGpsPoints),
    [evuaStations, govmapPoints, driverGpsPoints],
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedItem, setSelectedItem] = useState(null);
  const [ownerInfo, setOwnerInfo] = useState(null);
  const [ownerModalOpen, setOwnerModalOpen] = useState(false);
  const [requestLoading, setRequestLoading] = useState(false);
  const [paymentError, setPaymentError] = useState("");
  const [heatmapPayModalOpen, setHeatmapPayModalOpen] = useState(false);
  const [heatmapPaymentLoading, setHeatmapPaymentLoading] = useState(false);
  const [heatmapPaymentError, setHeatmapPaymentError] = useState("");
  const ownerPdfDownloadKeyRef = useRef("");

  const allItems = useMemo(
    () => [...items, ...lookingItems, ...pendingItems],
    [items, lookingItems, pendingItems],
  );
  itemsRef.current = allItems;
  heatmapPointsRef.current = heatmapPoints;
  heatmapZoomUnlockedRef.current = heatmapZoomUnlocked;
  const points = useMemo(
    () => [
      ...flattenLocations(items),
      ...flattenLocations(lookingItems),
      ...flattenLocations(pendingItems),
    ],
    [items, lookingItems, pendingItems],
  );
  pointsRef.current = points;
  const showHeatmapLegend = heatmapDataEnabled && heatmapPoints.length > 0;
  const showHeatmapPayButton = heatmapEnabled && !heatmapZoomUnlocked;

  const openOwnerInfo = useCallback((info) => {
    if (!info) return;
    setOwnerInfo(info);
    setOwnerModalOpen(true);
  }, []);

  useEffect(() => {
    if (!ownerModalOpen) {
      ownerPdfDownloadKeyRef.current = "";
    }
  }, [ownerModalOpen]);

  useEffect(() => {
    if (!ownerModalOpen || !ownerInfo?.distribution_contract_photos?.length)
      return undefined;

    const downloadKey = `${ownerInfo.name || ""}:${ownerInfo.distribution_contract_photos.join("|")}`;
    if (ownerPdfDownloadKeyRef.current === downloadKey) return undefined;
    ownerPdfDownloadKeyRef.current = downloadKey;

    const photoUrls = ownerInfo.distribution_contract_photos.map(
      resolveMarketplaceAssetUrl,
    );
    downloadContractPhotosAsPdf(photoUrls, ownerInfo.name).catch(() => {});

    return undefined;
  }, [ownerModalOpen, ownerInfo]);

  const upsertItemViewCount = useCallback((locationId, viewCount) => {
    if (!locationId) return;
    const patch = (row) =>
      String(row.id) === String(locationId)
        ? { ...row, view_count: viewCount }
        : row;
    setItems((prev) => prev.map(patch));
    setLookingItems((prev) => prev.map(patch));
    setSelectedItem((prev) =>
      prev && String(prev.id) === String(locationId)
        ? { ...prev, view_count: viewCount }
        : prev,
    );
  }, []);

  const resolveOwnerInfoFromPayment = useCallback(
    async (paymentId, locationId) => {
      const status = await fetchMarketplacePaymentStatus(paymentId);
      if (!status) throw new Error("missing status");

      if (
        locationId &&
        status.location_id &&
        String(status.location_id) !== String(locationId)
      ) {
        throw new Error("payment location mismatch");
      }

      if (status.owner_info?.view_count != null && status.location_id) {
        upsertItemViewCount(status.location_id, status.owner_info.view_count);
      }

      if (status.status === PAYMENT_SUCCESS && status.owner_info) {
        const resolvedLocationId = locationId || status.location_id;
        if (resolvedLocationId) {
          storeMarketplaceUnlockedPayment(resolvedLocationId, paymentId);
        }
        openOwnerInfo(status.owner_info);
        return true;
      }

      if (PAYMENT_FAILED.has(status.status)) {
        setPaymentError(t("marketplacePayFailed"));
        return false;
      }

      return null;
    },
    [openOwnerInfo, t, upsertItemViewCount],
  );

  const pollPaymentUntilDone = useCallback(
    async (paymentId, locationId) => {
      const maxAttempts = 20;
      for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
        // eslint-disable-next-line no-await-in-loop
        const result = await resolveOwnerInfoFromPayment(paymentId, locationId);
        if (result !== null) return result;
        // eslint-disable-next-line no-await-in-loop
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }
      setPaymentError(t("marketplacePayProcessing"));
      return false;
    },
    [resolveOwnerInfoFromPayment, t],
  );

  const handleMarkerSelect = useCallback((point) => {
    const item = itemsRef.current.find(
      (row) => String(row.id) === String(point.itemId),
    );
    if (item) setSelectedItem(item);
  }, []);

  const requestHeatmapSync = useCallback(
    (map, points) => {
      if (!map || !heatmapEnabled) return;

      const generation = heatmapSyncGenerationRef.current + 1;
      heatmapSyncGenerationRef.current = generation;

      const run = () => {
        if (heatmapSyncGenerationRef.current !== generation) return;
        if (mapRef.current !== map) return;
        // MapTiler can finish the load event before style.loaded() is true.
        // Wait for idle instead of dropping the sync.
        if (!isMapHeatmapReady(map)) {
          map.once("idle", run);
          return;
        }
        if (!heatmapZoomUnlockedRef.current) {
          removeHeatmapLayer(map);
          lastHeatmapSyncKeyRef.current = "";
          return;
        }
        heatmapRegionsRef.current = syncHeatmapLayerData(
          map,
          points,
          map.getZoom(),
          true,
          lastHeatmapSyncKeyRef,
        );
      };

      run();
    },
    [heatmapEnabled],
  );

  const refreshHeatmapOnMap = useCallback(() => {
    const map = mapRef.current;
    if (!map || !heatmapEnabled) return;
    if (!heatmapZoomUnlockedRef.current) {
      removeHeatmapLayer(map);
      lastHeatmapSyncKeyRef.current = "";
      return;
    }
    requestHeatmapSync(map, heatmapPointsRef.current);
  }, [requestHeatmapSync, heatmapEnabled]);

  const closeHeatmapPayModal = useCallback(() => {
    setHeatmapPayModalOpen(false);
    refreshHeatmapOnMap();
  }, [refreshHeatmapOnMap]);

  const applyHeatmapZoomUnlock = useCallback(
    (paymentId) => {
      storeHeatmapZoomUnlock(paymentId);
      setHeatmapZoomUnlocked(true);
      setHeatmapPayModalOpen(false);
      setHeatmapPaymentError("");
      refreshHeatmapOnMap();
    },
    [refreshHeatmapOnMap],
  );

  const resolveHeatmapPaymentUnlock = useCallback(
    async (paymentId) => {
      const status = await fetchMarketplacePaymentStatus(paymentId);
      if (!status) throw new Error("missing status");
      if (status.payment_kind && status.payment_kind !== "heatmap_zoom") {
        throw new Error("payment kind mismatch");
      }
      if (status.status === PAYMENT_SUCCESS) {
        applyHeatmapZoomUnlock(status.payment_id || paymentId);
        return true;
      }
      if (PAYMENT_FAILED.has(status.status)) {
        setHeatmapPaymentError(t("marketplacePayFailed"));
        return false;
      }
      return null;
    },
    [applyHeatmapZoomUnlock, t],
  );

  const pollHeatmapPaymentUntilDone = useCallback(
    async (paymentId) => {
      const maxAttempts = 20;
      for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
        // eslint-disable-next-line no-await-in-loop
        const result = await resolveHeatmapPaymentUnlock(paymentId);
        if (result !== null) return result;
        // eslint-disable-next-line no-await-in-loop
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }
      setHeatmapPaymentError(t("marketplacePayProcessing"));
      return false;
    },
    [resolveHeatmapPaymentUnlock, t],
  );

  useEffect(() => {
    if (!loadEvuaHeatmap || !isMarketplaceApiConfigured()) return undefined;

    let cancelled = false;
    setLoading(true);
    setError("");

    const fetches = [fetchMarketplaceLocations(requestType)];
    if (showLookingMarkers && requestType !== "LOOKING") {
      fetches.push(fetchMarketplaceLocations("LOOKING"));
    }

    Promise.all(fetches)
      .then((results) => {
        if (cancelled) return;
        setItems(results[0] || []);
        setLookingItems(
          showLookingMarkers && requestType !== "LOOKING"
            ? results[1] || []
            : [],
        );
      })
      .catch(() => {
        if (!cancelled) setError(t("marketplaceLoadError"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [loadEvuaHeatmap, requestType, showLookingMarkers, t]);

  useEffect(() => {
    if (!loadEvuaHeatmap || !isMarketplaceApiConfigured()) return undefined;

    let cancelled = false;
    // Pending submissions are a side list: a failure here must not hide published locations.
    fetchPendingMarketplaceLocations()
      .then((rows) => {
        if (!cancelled) setPendingItems(rows || []);
      })
      .catch(() => {
        if (!cancelled) setPendingItems([]);
      });

    return () => {
      cancelled = true;
    };
  }, [loadEvuaHeatmap]);

  useEffect(() => {
    if (!loadEvuaHeatmap || mapRef.current || !mapContainerRef.current)
      return undefined;

    maptilersdk.config.apiKey = MAPTILER_API_KEY;
    const map = new maptilersdk.Map({
      container: mapContainerRef.current,
      // Satellite plus vector borders, cities, districts, and streets.
      style: maptilersdk.MapStyle.HYBRID,
      language: resolveMapLanguage(locale),
      center: UKRAINE_CENTER,
      zoom: DEFAULT_ZOOM,
      geolocateControl: false,
      navigationControl: false,
      maptilerLogo: false,
      attributionControl: false,
      maxZoom: 21,
    });

    mapRef.current = map;

    const resizeMap = () => {
      if (mapRef.current === map) map.resize();
    };
    const resizeObserver =
      typeof ResizeObserver !== "undefined" && mapContainerRef.current
        ? new ResizeObserver(resizeMap)
        : null;
    if (resizeObserver && mapContainerRef.current) {
      resizeObserver.observe(mapContainerRef.current);
    }
    window.addEventListener("resize", resizeMap);

    map.addControl(
      new maplibregl.ScaleControl({
        maxWidth: HEATMAP_SCALE_BAR_MAX_PX,
        unit: "metric",
      }),
      "bottom-right",
    );

    const syncHeatmapAfterZoom = () => {
      if (!heatmapZoomUnlockedRef.current) {
        removeHeatmapLayer(map);
        lastHeatmapSyncKeyRef.current = "";
        return;
      }
      requestHeatmapSync(map, heatmapPointsRef.current);
    };

    const enforcePaidZoom = () => {
      if (heatmapZoomUnlockedRef.current || restoringZoomRef.current) return;
      if (!isZoomedCloserThanHeatmapScale(map)) {
        lastAllowedZoomRef.current = map.getZoom();
        return;
      }
      restoringZoomRef.current = true;
      setHeatmapPayModalOpen(true);
      const restoreZoom = Math.min(
        lastAllowedZoomRef.current,
        heatmapLockMaxZoom(map),
      );
      try {
        if (typeof map.stop === "function") map.stop();
        map.jumpTo({ zoom: restoreZoom });
      } finally {
        restoringZoomRef.current = false;
      }
    };

    const openZoomPaywall = (event) => {
      if (heatmapZoomUnlockedRef.current) return;
      const delta = event?.originalEvent?.deltaY;
      if (typeof delta === "number" && delta >= 0) return;
      if (map.getZoom() < heatmapLockMaxZoom(map) - 0.08) return;
      setHeatmapPayModalOpen(true);
    };

    map.on("load", () => {
      setMapReady(true);
      lastAllowedZoomRef.current = map.getZoom();
      if (
        !heatmapZoomUnlockedRef.current &&
        typeof map.setMaxZoom === "function"
      ) {
        map.setMaxZoom(heatmapLockMaxZoom(map));
      }
      resizeMap();
      syncMarketplaceMarkers(
        map,
        pointsRef.current,
        handleMarkerSelect,
        htmlMarkersRef,
        styles,
      );
      syncHeatmapAfterZoom();
    });

    map.on("zoom", enforcePaidZoom);
    map.on("wheel", openZoomPaywall);
    map.on("dblclick", openZoomPaywall);
    map.on("zoomend", syncHeatmapAfterZoom);

    return () => {
      heatmapSyncGenerationRef.current += 1;
      lastHeatmapSyncKeyRef.current = "";
      resizeObserver?.disconnect();
      window.removeEventListener("resize", resizeMap);
      map.off("zoom", enforcePaidZoom);
      map.off("wheel", openZoomPaywall);
      map.off("dblclick", openZoomPaywall);
      map.off("zoomend", syncHeatmapAfterZoom);
      removeHeatmapLayer(map);
      removeMarketplaceMarkers(htmlMarkersRef);
      setMapReady(false);
      map.remove();
      mapRef.current = null;
    };
  }, [
    loadEvuaHeatmap,
    handleMarkerSelect,
    showLookingHeatmap,
    requestHeatmapSync,
    heatmapEnabled,
    locale,
  ]);

  useEffect(() => {
    const map = mapRef.current;
    if (!mapReady || !map || typeof map.setMaxZoom !== "function") return;
    map.setMaxZoom(heatmapZoomUnlocked ? 21 : heatmapLockMaxZoom(map));
  }, [heatmapZoomUnlocked, mapReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!loadEvuaHeatmap || !mapReady || !map) return;
    syncMarketplaceMarkers(
      map,
      points,
      handleMarkerSelect,
      htmlMarkersRef,
      styles,
    );
  }, [loadEvuaHeatmap, mapReady, points, handleMarkerSelect]);

  useEffect(() => {
    const map = mapRef.current;
    if (!mapReady || !map || !heatmapDataEnabled) {
      if (mapReady && map) removeHeatmapLayer(map);
      return;
    }
    lastHeatmapSyncKeyRef.current = "";
    requestHeatmapSync(map, heatmapPoints);
  }, [heatmapPoints, heatmapDataEnabled, mapReady, requestHeatmapSync]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !selectedItem) return undefined;

    const onMapClick = () => {
      setSelectedItem(null);
    };

    map.on("click", onMapClick);
    return () => {
      map.off("click", onMapClick);
    };
  }, [selectedItem]);

  useEffect(() => {
    if (
      !paymentReturnLocationId ||
      (items.length === 0 && lookingItems.length === 0)
    )
      return;
    const item =
      items.find((row) => String(row.id) === String(paymentReturnLocationId)) ||
      lookingItems.find(
        (row) => String(row.id) === String(paymentReturnLocationId),
      );
    if (item) setSelectedItem(item);
  }, [paymentReturnLocationId, items, lookingItems]);

  useEffect(() => {
    if (!paymentReturnId || !isMarketplaceApiConfigured()) return undefined;

    let cancelled = false;
    setRequestLoading(true);
    setPaymentError("");

    pollPaymentUntilDone(paymentReturnId, paymentReturnLocationId)
      .then(() => {
        if (!cancelled) onPaymentReturnHandled?.();
      })
      .catch(() => {
        if (!cancelled) setPaymentError(t("marketplacePayFailed"));
      })
      .finally(() => {
        if (!cancelled) setRequestLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [
    paymentReturnId,
    paymentReturnLocationId,
    onPaymentReturnHandled,
    pollPaymentUntilDone,
    t,
  ]);

  useEffect(() => {
    if (!heatmapPaymentReturnId || !isMarketplaceApiConfigured())
      return undefined;

    let cancelled = false;
    setHeatmapPaymentLoading(true);
    setHeatmapPaymentError("");

    pollHeatmapPaymentUntilDone(heatmapPaymentReturnId)
      .then(() => {
        if (!cancelled) onHeatmapPaymentReturnHandled?.();
      })
      .catch(() => {
        if (!cancelled) setHeatmapPaymentError(t("marketplacePayFailed"));
      })
      .finally(() => {
        if (!cancelled) setHeatmapPaymentLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [
    heatmapPaymentReturnId,
    onHeatmapPaymentReturnHandled,
    pollHeatmapPaymentUntilDone,
    t,
  ]);

  const handleRequestInfo = async () => {
    if (!selectedItem || requestLoading) return;
    setRequestLoading(true);
    setPaymentError("");

    const storedPaymentId = getStoredMarketplacePaymentId(selectedItem.id);
    if (storedPaymentId) {
      try {
        const unlocked = await resolveOwnerInfoFromPayment(
          storedPaymentId,
          selectedItem.id,
        );
        if (unlocked) {
          setRequestLoading(false);
          return;
        }
      } catch {
        /* fall through to new payment */
      }
    }

    try {
      const payment = await createMarketplaceInfoPayment(selectedItem.id, {
        redirectBaseUrl: buildMarketplacePayRedirectBase(),
        clientUiId: getClientId(),
      });
      if (payment?.page_url) {
        window.location.href = payment.page_url;
        return;
      }
      setPaymentError(t("marketplacePayFailed"));
    } catch {
      setPaymentError(t("marketplacePayFailed"));
    } finally {
      setRequestLoading(false);
    }
  };

  const handleSkipPaymentTest = async () => {
    if (!selectedItem || requestLoading) return;
    setRequestLoading(true);
    setPaymentError("");
    try {
      const status = await createMarketplaceTestPayment(selectedItem.id, {
        clientUiId: getClientId(),
      });
      if (status?.payment_id) {
        const unlocked = await resolveOwnerInfoFromPayment(
          status.payment_id,
          selectedItem.id,
        );
        if (!unlocked) {
          setPaymentError(t("marketplacePayFailed"));
        }
        return;
      }
      setPaymentError(t("marketplacePayFailed"));
    } catch {
      setPaymentError(t("marketplacePayFailed"));
    } finally {
      setRequestLoading(false);
    }
  };

  const handleHeatmapPay = async () => {
    if (heatmapPaymentLoading) return;
    setHeatmapPaymentLoading(true);
    setHeatmapPaymentError("");
    try {
      const payment = await createHeatmapZoomPayment({
        redirectBaseUrl: buildMarketplacePayRedirectBase(),
        clientUiId: getClientId(),
      });
      if (payment?.page_url) {
        window.location.href = payment.page_url;
        return;
      }
      setHeatmapPaymentError(t("marketplacePayFailed"));
    } catch {
      setHeatmapPaymentError(t("marketplacePayFailed"));
    } finally {
      setHeatmapPaymentLoading(false);
    }
  };

  const handleHeatmapPayTest = async () => {
    if (heatmapPaymentLoading) return;
    setHeatmapPaymentLoading(true);
    setHeatmapPaymentError("");
    try {
      const status = await createHeatmapZoomTestPayment({
        clientUiId: getClientId(),
      });
      if (status?.status === PAYMENT_SUCCESS && status?.payment_id) {
        applyHeatmapZoomUnlock(status.payment_id);
        return;
      }
      setHeatmapPaymentError(t("marketplacePayFailed"));
    } catch {
      if (isMarketplaceUiLocalDev()) {
        storeHeatmapZoomUnlockLocalDev();
        applyHeatmapZoomUnlock("local-dev");
        return;
      }
      setHeatmapPaymentError(t("marketplacePayFailed"));
    } finally {
      setHeatmapPaymentLoading(false);
    }
  };

  const showLocalTestPayment = isMarketplaceLocalTestPaymentEnabled();
  const selectedIsPending = selectedItem?.status === "PENDING";
  const selectedIsLooking = selectedItem?.request_type === "LOOKING";
  const selectedDetailTitleKey = selectedIsPending
    ? "marketplaceDetailTitlePending"
    : selectedIsLooking
      ? "marketplaceDetailTitleLooking"
      : "marketplaceDetailTitlePropose";
  const selectedRequestInfoKey = selectedIsLooking
    ? "marketplaceRequestInvestorInfoPayButton"
    : "marketplaceRequestInfoPayButton";

  if (!isMarketplaceApiConfigured()) {
    return null;
  }

  return (
    <section
      className={`${styles.root}${hideHeader ? ` ${styles.rootEmbedded}` : ""}`}
      aria-labelledby={hideHeader ? undefined : "marketplace-map-title"}
    >
      {hideHeader ? null : (
        <>
          <h2 id="marketplace-map-title" className={styles.title}>
            {t("marketplaceTitle")}
          </h2>
          <p className={styles.subtitle}>{t("marketplaceMapHint")}</p>
        </>
      )}

      {loading ? (
        <p className={styles.status}>{t("marketplaceLeadFormMapLoading")}</p>
      ) : null}
      {error ? <p className={styles.error}>{error}</p> : null}

      <div className={styles.mapWrap}>
        <div
          ref={mapContainerRef}
          className={styles.map}
          aria-label={t("marketplaceMapAria")}
        />

        {showHeatmapPayButton ? (
          <button
            type="button"
            className={styles.heatmapUnlockBtn}
            onClick={() => setHeatmapPayModalOpen(true)}
          >
            <span className={styles.heatmapLegendTitle}>
              {t("marketplaceHeatmapLegendTitle")}
            </span>
            <span className={styles.heatmapUnlockPrice}>
              {t("marketplaceHeatmapPayButton", {
                amount: HEATMAP_PAY_AMOUNT_UAH,
              })}
            </span>
          </button>
        ) : null}

        {showHeatmapLegend ? (
          <div className={styles.heatmapLegend} aria-hidden>
            <span className={styles.heatmapLegendTitle}>
              {t("marketplaceHeatmapLegendTitle")}
            </span>
            <div className={styles.heatmapLegendScale}>
              <span className={styles.heatmapLegendLow}>
                {t("marketplaceHeatmapLegendLow")}
              </span>
              <span className={styles.heatmapLegendBar} />
              <span className={styles.heatmapLegendHigh}>
                {t("marketplaceHeatmapLegendHigh")}
              </span>
            </div>
          </div>
        ) : null}

        {selectedItem ? (
          <div
            className={styles.detailPanel}
            role="dialog"
            aria-label={t(selectedDetailTitleKey)}
            onClick={(e) => e.stopPropagation()}
          >
            <div className={styles.detailHeader}>
              <h3 className={styles.detailTitle}>
                {t(selectedDetailTitleKey)}
              </h3>
              <button
                type="button"
                className={styles.detailCloseBtn}
                onClick={() => setSelectedItem(null)}
                aria-label={t("marketplaceClose")}
              >
                ×
              </button>
            </div>

            {selectedIsPending ? (
              <>
                <div className={styles.detailBadges}>
                  <span className={styles.kwBadge}>
                    {formatKwLabel(selectedItem.kw_available)}
                  </span>
                </div>
                <p className={styles.pendingNote}>
                  {t("marketplacePendingReviewNote")}
                </p>
              </>
            ) : (
              <>
                <MarketplaceDetailsBody
                  item={selectedItem}
                  t={t}
                  language={locale}
                  variant="map"
                />

                <p className={styles.viewCount}>
                  {t("marketplaceViewedTimes", {
                    count: selectedItem.view_count || 0,
                  })}
                </p>

                {paymentError ? (
                  <p className={styles.paymentError}>{paymentError}</p>
                ) : null}

                <button
                  type="button"
                  className={styles.requestInfoBtn}
                  onClick={handleRequestInfo}
                  disabled={requestLoading}
                >
                  {requestLoading
                    ? t("marketplaceLeadFormMapLoading")
                    : t(selectedRequestInfoKey, {
                        amount: infoPaymentAmountUah(selectedItem.request_type),
                      })}
                </button>
                {showLocalTestPayment ? (
                  <button
                    type="button"
                    className={styles.payTestBtn}
                    onClick={handleSkipPaymentTest}
                    disabled={requestLoading}
                  >
                    {t("marketplacePayTestSkip")}
                  </button>
                ) : null}
              </>
            )}
          </div>
        ) : null}
      </div>

      {!loading && !error && items.length === 0 && lookingItems.length === 0 ? (
        <p className={styles.empty}>{t("marketplaceEmpty")}</p>
      ) : null}

      <MarketplaceModal
        open={ownerModalOpen}
        onClose={() => setOwnerModalOpen(false)}
        ariaLabel={t("marketplaceOwnerInfoTitle")}
        closeAriaLabel={t("marketplaceClose")}
      >
        <div className={styles.contactModal}>
          <h3 className={styles.contactTitle}>
            {t("marketplaceOwnerInfoTitle")}
          </h3>
          <OwnerInfoBody ownerInfo={ownerInfo} t={t} />
        </div>
      </MarketplaceModal>

      <MarketplaceModal
        open={heatmapPayModalOpen}
        onClose={closeHeatmapPayModal}
        ariaLabel={t("marketplaceHeatmapPayTitle")}
        closeAriaLabel={t("marketplaceClose")}
      >
        <div className={styles.heatmapPayModal}>
          <h3 className={styles.heatmapPayTitle}>
            {t("marketplaceHeatmapPayTitle")}
          </h3>
          <p className={styles.heatmapPayText}>
            {t("marketplaceHeatmapPayDescription", {
              amount: HEATMAP_PAY_AMOUNT_UAH,
            })}
          </p>
          {heatmapPaymentError ? (
            <p className={styles.paymentError}>{heatmapPaymentError}</p>
          ) : null}
          <button
            type="button"
            className={styles.requestInfoBtn}
            onClick={handleHeatmapPay}
            disabled={heatmapPaymentLoading}
          >
            {heatmapPaymentLoading
              ? t("marketplaceLeadFormMapLoading")
              : t("marketplaceHeatmapPayButton", {
                  amount: HEATMAP_PAY_AMOUNT_UAH,
                })}
          </button>
          {showLocalTestPayment ? (
            <button
              type="button"
              className={styles.payTestBtn}
              onClick={handleHeatmapPayTest}
              disabled={heatmapPaymentLoading}
            >
              {t("marketplaceHeatmapPayTestSkip")}
            </button>
          ) : null}
        </div>
      </MarketplaceModal>
    </section>
  );
}
