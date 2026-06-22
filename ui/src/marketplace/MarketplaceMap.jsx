import { useCallback, useEffect, useRef, useState } from 'react';
import * as maptilersdk from '@maptiler/sdk';
import maplibregl from 'maplibre-gl';
import '@maptiler/sdk/dist/maptiler-sdk.css';
import { getClientId } from './clientId';
import { formatDistanceMeters, buildGoogleMapsPointUrl } from './messengerLinks';
import {
  createMarketplaceInfoPayment,
  createMarketplaceTestPayment,
  fetchMarketplaceLocations,
  fetchMarketplacePaymentStatus,
  getStoredMarketplacePaymentId,
  isMarketplaceApiConfigured,
  isMarketplaceLocalTestPaymentEnabled,
  resolveMarketplaceAssetUrl,
  storeMarketplaceUnlockedPayment,
} from './marketplaceApi';
import { useEvua80KwStations } from './useEvua80KwStations';
import { downloadContractPhotosAsPdf } from './marketplaceContractPdf';
import MarketplaceModal from './MarketplaceModal';
import styles from './MarketplaceMap.module.css';

const MAPTILER_API_KEY = '1Lk2s9HJjoiXBR1oqw5a';
const MAPLIBRE_WORKER_URL = `${process.env.PUBLIC_URL || ''}/maplibre-gl-csp-worker.js`;
const UKRAINE_CENTER = [31.223, 49.454];
const DEFAULT_ZOOM = 6;
const HEATMAP_SOURCE_ID = 'b2b-marketplace-looking-heatmap';
const HEATMAP_LAYER_ID = 'b2b-marketplace-looking-heatmap-layer';
const HEATMAP_SCALE_BAR_MAX_PX = 120;
/** Hide heatmap when scale bar would read below 3 km (street-level zoom). */
const HEATMAP_MIN_SCALE_KM = 3;

if (typeof maplibregl.setWorkerUrl === 'function') {
  maplibregl.setWorkerUrl(MAPLIBRE_WORKER_URL);
}
/** Group EV UA coords; finer grid when zoomed in so single stations stay visible. */
const REGION_GROUP_PRECISION = 1;

function precisionForZoom(zoom) {
  if (zoom >= 12) return 3;
  if (zoom >= 9) return 2;
  return REGION_GROUP_PRECISION;
}

function buildHybridStyle(apiKey) {
  return {
    version: 8,
    sources: {
      'maptiler-raster': {
        type: 'raster',
        tiles: [`https://api.maptiler.com/maps/hybrid/256/{z}/{x}/{y}.jpg?key=${apiKey}`],
        tileSize: 256,
        attribution:
          '<a href="https://www.maptiler.com/copyright/" target="_blank" rel="noreferrer">© MapTiler</a> ' +
          '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">© OpenStreetMap</a>',
      },
    },
    layers: [
      {
        id: 'maptiler-raster',
        type: 'raster',
        source: 'maptiler-raster',
        minzoom: 0,
        maxzoom: 22,
      },
    ],
  };
}

function flattenLocations(items) {
  const points = [];
  (items || []).forEach(item => {
    const hasContract =
      item.distribution_contract === true ? 1 : item.distribution_contract === false ? 0 : -1;
    (item.locations || []).forEach((loc, index) => {
      points.push({
        id: `${item.id}-${index}`,
        itemId: String(item.id),
        lat: loc.lat,
        lng: loc.lng,
        label: loc.label,
        hasContract,
        kw: item.kw_available,
      });
    });
  });
  return points;
}

function formatMarkerKwLabel(kwAvailable) {
  const raw = String(kwAvailable || '').trim();
  if (!raw) return '—';
  return `${raw.replace(/\+$/, '')} kW`;
}

function createMarketplaceMarkerElement(point, styles) {
  const el = document.createElement('button');
  el.type = 'button';
  el.className = [
    styles.mapMarker,
    point.hasContract === 0 ? styles.mapMarkerContractNo : styles.mapMarkerContractYes,
  ].join(' ');
  el.textContent = formatMarkerKwLabel(point.kw);
  return el;
}

function removeMarketplaceMarkers(markersRef) {
  markersRef.current.forEach(marker => marker.remove());
  markersRef.current = [];
}

function syncMarketplaceMarkers(map, points, onSelect, markersRef, styles) {
  removeMarketplaceMarkers(markersRef);
  if (!map || !points?.length) return;

  points.forEach(point => {
    const el = createMarketplaceMarkerElement(point, styles);
    el.addEventListener('click', event => {
      event.stopPropagation();
      onSelect(point);
    });
    const marker = new maptilersdk.Marker({ element: el, anchor: 'center' })
      .setLngLat([point.lng, point.lat])
      .addTo(map);
    markersRef.current.push(marker);
  });
}

function heatmapPointsToGeoJson(regions) {
  return {
    type: 'FeatureCollection',
    features: (regions || []).map(region => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [region.lng, region.lat] },
      properties: { weight: region.weight },
    })),
  };
}

/** Aggregate EV UA station coords into grid hotspots (weight = stations per cell). */
function aggregateEvuaHeatmapPoints(stations, groupPrecision = REGION_GROUP_PRECISION) {
  const groups = new Map();
  (stations || []).forEach(station => {
    const lat = Number(station?.lat);
    const lng = Number(station?.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
    const key = `${lat.toFixed(groupPrecision)}:${lng.toFixed(groupPrecision)}`;
    const existing = groups.get(key);
    if (existing) {
      existing.weight += 1;
      existing.lat += lat;
      existing.lng += lng;
      existing.count += 1;
    } else {
      groups.set(key, { weight: 1, lat, lng, count: 1 });
    }
  });

  const raw = Array.from(groups.values()).map(group => ({
    lat: group.lat / group.count,
    lng: group.lng / group.count,
    count: group.weight,
  }));
  if (!raw.length) return [];

  // Zoomed-in grid: keep every cell visible, including count === 1.
  if (groupPrecision >= 2) {
    const maxCount = Math.max(...raw.map(group => group.count));
    const logMax = Math.log1p(maxCount);
    return raw.map(group => ({
      lat: group.lat,
      lng: group.lng,
      weight: logMax > 0 ? Math.max(0.42, Math.log1p(group.count) / logMax) : 0.42,
    }));
  }

  const sortedCounts = raw.map(group => group.count).sort((a, b) => a - b);
  const topWarmStartIndex = Math.max(0, Math.ceil(sortedCounts.length * 0.5) - 1);
  const topWarmThreshold = sortedCounts[topWarmStartIndex] ?? sortedCounts[sortedCounts.length - 1];
  const maxCount = sortedCounts[sortedCounts.length - 1];
  const logTopWarm = Math.log1p(topWarmThreshold);
  const logMax = Math.log1p(maxCount);

  return raw.map(group => {
    const logCount = Math.log1p(group.count);
    let weight;

    if (logCount <= logTopWarm || logMax <= logTopWarm) {
      // Bottom ~50%: blue → green → yellow on the map.
      weight = logTopWarm > 0 ? (logCount / logTopWarm) * 0.55 : 0.2;
    } else {
      // Top ~50%: orange → red; log keeps dense vs sparse cities distinguishable.
      const topSpan = logMax - logTopWarm;
      weight = topSpan > 0 ? 0.55 + ((logCount - logTopWarm) / topSpan) * 0.45 : 1;
    }

    return { lat: group.lat, lng: group.lng, weight };
  });
}

const HEATMAP_PAINT = {
  'heatmap-weight': ['interpolate', ['linear'], ['get', 'weight'], 0, 0, 0.4, 0.5, 0.75, 0.75, 1, 1],
  'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 4, 0.45, 6, 0.65, 9, 1.2, 11, 1.9, 13, 2.6],
  'heatmap-color': [
    'interpolate',
    ['linear'],
    ['heatmap-density'],
    0,
    'rgba(33, 102, 172, 0)',
    0.08,
    'rgba(103, 169, 207, 0.5)',
    0.18,
    'rgb(140, 211, 175)',
    0.3,
    'rgb(253, 219, 99)',
    0.42,
    'rgb(244, 109, 67)',
    0.52,
    'rgb(215, 25, 28)',
  ],
  'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 4, 12, 6, 18, 9, 28, 11, 38, 13, 52],
  'heatmap-opacity': 0.65,
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
  return Boolean(map && typeof map.loaded === 'function' && map.loaded());
}

function getMapScaleBarKm(map, scaleBarCssPx = HEATMAP_SCALE_BAR_MAX_PX) {
  if (!map || typeof map.getCenter !== 'function' || typeof map.getZoom !== 'function') {
    return Number.POSITIVE_INFINITY;
  }
  const center = map.getCenter();
  const zoom = map.getZoom();
  const latRad = (center.lat * Math.PI) / 180;
  const metersPerPixel = (40075016.686 * Math.cos(latRad)) / (512 * 2 ** zoom);
  return (scaleBarCssPx * metersPerPixel) / 1000;
}

function shouldShowHeatmapAtMapScale(map) {
  return getMapScaleBarKm(map) >= HEATMAP_MIN_SCALE_KM;
}

function upsertHeatmapLayer(map, regions) {
  if (!regions?.length) {
    removeHeatmapLayer(map);
    return;
  }
  if (!isMapHeatmapReady(map)) return;

  const data = heatmapPointsToGeoJson(regions);
  removeHeatmapLayer(map);
  map.addSource(HEATMAP_SOURCE_ID, { type: 'geojson', data });
  map.addLayer({
    id: HEATMAP_LAYER_ID,
    type: 'heatmap',
    source: HEATMAP_SOURCE_ID,
    paint: HEATMAP_PAINT,
  });
}

function syncHeatmapLayerData(map, stations, zoom) {
  const regions = aggregateEvuaHeatmapPoints(stations, precisionForZoom(zoom));
  if (!isMapHeatmapReady(map)) {
    return regions;
  }

  if (!shouldShowHeatmapAtMapScale(map) || !regions.length) {
    removeHeatmapLayer(map);
    return regions;
  }

  try {
    upsertHeatmapLayer(map, regions);
  } catch {
    removeHeatmapLayer(map);
  }
  return regions;
}

function formatContract(value, t) {
  if (value === true) return t('marketplaceLeadFormYes');
  if (value === false) return t('marketplaceLeadFormNo');
  return '—';
}

function marketplaceRelativeTimeLocale(language) {
  const lang = String(language || '').toLowerCase();
  if (lang.startsWith('uk') || lang.startsWith('ua')) return 'uk';
  if (lang.startsWith('ru')) return 'ru';
  return 'en';
}

function formatMarketplacePublicationRelative(isoDate, language) {
  if (!isoDate) return '';
  const date = new Date(isoDate);
  if (Number.isNaN(date.getTime())) return '';

  const diffMs = Date.now() - date.getTime();
  if (diffMs < 0) return '';

  const rtf = new Intl.RelativeTimeFormat(marketplaceRelativeTimeLocale(language), { numeric: 'always' });
  const diffMinutes = Math.floor(diffMs / (1000 * 60));
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays >= 365) {
    return rtf.format(-Math.floor(diffDays / 365), 'year');
  }
  if (diffDays >= 30) {
    return rtf.format(-Math.floor(diffDays / 30), 'month');
  }
  if (diffDays >= 1) {
    return rtf.format(-diffDays, 'day');
  }
  if (diffHours >= 1) {
    return rtf.format(-diffHours, 'hour');
  }
  return rtf.format(-Math.max(1, diffMinutes), 'minute');
}

function MarketplaceDetailsBody({ item, t, variant = 'full', language = 'ua' }) {
  const photoSections =
    variant === 'map'
      ? [
          {
            key: 'connection',
            photos: item.connection_point_photos,
            label: t('marketplaceMapConnectionPhotos'),
          },
          {
            key: 'parking',
            photos: item.parking_photos,
            label: t('marketplaceMapParkingPhotos'),
          },
        ]
      : [
          {
            key: 'parking',
            photos: item.parking_photos,
            label: t('marketplaceLeadFormParkingPhotosLabel'),
          },
          {
            key: 'connection',
            photos: item.connection_point_photos,
            label: t('marketplaceLeadFormConnectionPhotosLabel'),
          },
          {
            key: 'distribution',
            photos: item.distribution_contract_photos,
            label: t('marketplaceDistributionContractPhotosLabel'),
          },
        ];
  const visiblePhotoSections = photoSections.filter(section => section.photos?.length > 0);
  const publicationRelative = formatMarketplacePublicationRelative(item.published_on || item.created_on, language);

  return (
    <>
      <div className={styles.detailBadges}>
        <span className={styles.kwBadge}>{t('marketplaceMapKw', { value: item.kw_available })}</span>
        {item.distribution_contract != null ? (
          <span
            className={`${styles.contractBadge} ${
              item.distribution_contract ? styles.contractBadgeYes : styles.contractBadgeNo
            }`}
          >
            {t('marketplaceLeadFormDistributionLabel')}: {formatContract(item.distribution_contract, t)}
          </span>
        ) : null}
        {item.distance_meters != null ? (
          <span className={styles.distanceBadge}>
            {t('marketplaceLeadFormDistanceLabel')}: {formatDistanceMeters(item.distance_meters, t)}
          </span>
        ) : null}
        {item.price_per_kwh_extra != null ? (
          <span className={styles.distanceBadge}>
            {t('marketplaceLeadFormPriceKwhExtraLabel')}: {Number(item.price_per_kwh_extra).toFixed(1)} ₴
          </span>
        ) : null}
        {item.monthly_price_parking != null ? (
          <span className={styles.distanceBadge}>
            {t('marketplaceLeadFormMonthlyParkingLabel')}: {item.monthly_price_parking} ₴
          </span>
        ) : null}
      </div>

      {publicationRelative ? (
        <p className={styles.publicationDate}>{t('marketplacePublishedOn', { timeAgo: publicationRelative })}</p>
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

      {visiblePhotoSections.length > 0 ? (
        <div className={styles.photoGroups}>
          {visiblePhotoSections.map(section => (
            <div key={section.key} className={styles.photoGroup}>
              <span className={styles.photoGroupLabel}>{section.label}</span>
              <div className={styles.photoRow}>
                {section.photos.map(url => (
                  <a key={url} href={resolveMarketplaceAssetUrl(url)} target="_blank" rel="noopener noreferrer">
                    <img src={resolveMarketplaceAssetUrl(url)} alt="" className={styles.photoThumb} />
                  </a>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </>
  );
}

function OwnerInfoBody({ ownerInfo, t }) {
  if (!ownerInfo) return null;

  const contractPhotos = (ownerInfo.distribution_contract_photos || []).filter(Boolean);

  return (
    <div className={styles.ownerInfoBody}>
      <div className={styles.ownerInfoRow}>
        <span className={styles.ownerInfoLabel}>{t('marketplaceOwnerName')}</span>
        <span className={styles.ownerInfoValue}>{ownerInfo.name}</span>
      </div>
      <div className={styles.ownerInfoRow}>
        <span className={styles.ownerInfoLabel}>{t('marketplaceOwnerPhone')}</span>
        <a className={styles.ownerInfoPhone} href={`tel:${ownerInfo.phone}`}>
          {ownerInfo.phone}
        </a>
      </div>
      {contractPhotos.length > 0 ? (
        <div className={styles.photoGroup}>
          <span className={styles.photoGroupLabel}>{t('marketplaceDistributionContractPhotosLabel')}</span>
          <div className={styles.photoRow}>
            {contractPhotos.map(url => (
              <a key={url} href={resolveMarketplaceAssetUrl(url)} target="_blank" rel="noopener noreferrer">
                <img src={resolveMarketplaceAssetUrl(url)} alt="" className={styles.photoThumbLarge} />
              </a>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

const PAYMENT_SUCCESS = 'SUCCESS';
const PAYMENT_FAILED = new Set(['FAILURE', 'EXPIRED', 'REVERSED']);

function buildMarketplacePayRedirectBase() {
  if (typeof window === 'undefined') return '/marketplace';
  return `${window.location.origin}/marketplace`;
}

export default function MarketplaceMap({
  t,
  locale = 'uk',
  requestType = 'PROPOSE',
  hideHeader = false,
  showLookingHeatmap = true,
  loadEvuaHeatmap = false,
  paymentReturnId = '',
  paymentReturnLocationId = '',
  onPaymentReturnHandled,
}) {
  const mapContainerRef = useRef(null);
  const mapRef = useRef(null);
  const htmlMarkersRef = useRef([]);
  const itemsRef = useRef([]);
  const pointsRef = useRef([]);
  const heatmapRegionsRef = useRef([]);
  const evuaStationsRef = useRef([]);
  const heatmapSyncGenerationRef = useRef(0);
  const [mapReady, setMapReady] = useState(false);
  const [items, setItems] = useState([]);
  const { stations: evuaStations } = useEvua80KwStations(showLookingHeatmap && loadEvuaHeatmap);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selectedItem, setSelectedItem] = useState(null);
  const [ownerInfo, setOwnerInfo] = useState(null);
  const [ownerModalOpen, setOwnerModalOpen] = useState(false);
  const [requestLoading, setRequestLoading] = useState(false);
  const [paymentError, setPaymentError] = useState('');
  const [heatmapAtScale, setHeatmapAtScale] = useState(true);
  const ownerPdfDownloadKeyRef = useRef('');

  itemsRef.current = items;
  evuaStationsRef.current = evuaStations;
  const points = flattenLocations(items);
  pointsRef.current = points;
  const hasHeatmapData = showLookingHeatmap && loadEvuaHeatmap && evuaStations.length > 0;
  const showHeatmapLegend = hasHeatmapData && heatmapAtScale;

  const openOwnerInfo = useCallback(info => {
    if (!info) return;
    setOwnerInfo(info);
    setOwnerModalOpen(true);
  }, []);

  useEffect(() => {
    if (!ownerModalOpen) {
      ownerPdfDownloadKeyRef.current = '';
    }
  }, [ownerModalOpen]);

  useEffect(() => {
    if (!ownerModalOpen || !ownerInfo?.distribution_contract_photos?.length) return undefined;

    const downloadKey = `${ownerInfo.name || ''}:${ownerInfo.distribution_contract_photos.join('|')}`;
    if (ownerPdfDownloadKeyRef.current === downloadKey) return undefined;
    ownerPdfDownloadKeyRef.current = downloadKey;

    const photoUrls = ownerInfo.distribution_contract_photos.map(resolveMarketplaceAssetUrl);
    downloadContractPhotosAsPdf(photoUrls, ownerInfo.name).catch(() => {});

    return undefined;
  }, [ownerModalOpen, ownerInfo]);

  const upsertItemViewCount = useCallback((locationId, viewCount) => {
    if (!locationId) return;
    setItems(prev =>
      prev.map(row => (String(row.id) === String(locationId) ? { ...row, view_count: viewCount } : row))
    );
    setSelectedItem(prev =>
      prev && String(prev.id) === String(locationId) ? { ...prev, view_count: viewCount } : prev
    );
  }, []);

  const resolveOwnerInfoFromPayment = useCallback(
    async (paymentId, locationId) => {
      const status = await fetchMarketplacePaymentStatus(paymentId);
      if (!status) throw new Error('missing status');

      if (locationId && status.location_id && String(status.location_id) !== String(locationId)) {
        throw new Error('payment location mismatch');
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
        setPaymentError(t('marketplacePayFailed'));
        return false;
      }

      return null;
    },
    [openOwnerInfo, t, upsertItemViewCount]
  );

  const pollPaymentUntilDone = useCallback(
    async (paymentId, locationId) => {
      const maxAttempts = 20;
      for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
        // eslint-disable-next-line no-await-in-loop
        const result = await resolveOwnerInfoFromPayment(paymentId, locationId);
        if (result !== null) return result;
        // eslint-disable-next-line no-await-in-loop
        await new Promise(resolve => setTimeout(resolve, 1500));
      }
      setPaymentError(t('marketplacePayProcessing'));
      return false;
    },
    [resolveOwnerInfoFromPayment, t]
  );

  const handleMarkerSelect = useCallback(point => {
    const item = itemsRef.current.find(row => String(row.id) === String(point.itemId));
    if (item) setSelectedItem(item);
  }, []);

  const requestHeatmapSync = useCallback(
    (map, stations) => {
      if (!map || !showLookingHeatmap || !loadEvuaHeatmap) return;

      const generation = heatmapSyncGenerationRef.current + 1;
      heatmapSyncGenerationRef.current = generation;

      const run = () => {
        if (heatmapSyncGenerationRef.current !== generation) return;
        if (mapRef.current !== map || !isMapHeatmapReady(map)) return;
        if (!showLookingHeatmap || !loadEvuaHeatmap) return;
        heatmapRegionsRef.current = syncHeatmapLayerData(map, stations, map.getZoom());
      };

      if (isMapHeatmapReady(map)) {
        map.once('idle', run);
      } else {
        map.once('load', () => map.once('idle', run));
      }
    },
    [showLookingHeatmap, loadEvuaHeatmap]
  );

  useEffect(() => {
    if (!loadEvuaHeatmap || !isMarketplaceApiConfigured()) return undefined;

    let cancelled = false;
    setLoading(true);
    setError('');

    fetchMarketplaceLocations(requestType)
      .then(data => {
        if (!cancelled) setItems(data);
      })
      .catch(() => {
        if (!cancelled) setError(t('marketplaceLoadError'));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [loadEvuaHeatmap, requestType, t]);

  useEffect(() => {
    if (!loadEvuaHeatmap || mapRef.current || !mapContainerRef.current) return undefined;

    maptilersdk.config.apiKey = MAPTILER_API_KEY;
    const map = new maptilersdk.Map({
      container: mapContainerRef.current,
      style: buildHybridStyle(MAPTILER_API_KEY),
      center: UKRAINE_CENTER,
      zoom: DEFAULT_ZOOM,
      geolocateControl: false,
      navigationControl: false,
      maptilerLogo: false,
      attributionControl: true,
      maxZoom: 21,
    });

    mapRef.current = map;

    map.addControl(new maplibregl.ScaleControl({ maxWidth: HEATMAP_SCALE_BAR_MAX_PX, unit: 'metric' }), 'bottom-right');

    const syncHeatmapScaleVisibility = () => {
      const visible = shouldShowHeatmapAtMapScale(map);
      setHeatmapAtScale(visible);
      if (!visible) removeHeatmapLayer(map);
    };

    const refreshHeatmap = () => {
      requestHeatmapSync(map, evuaStationsRef.current);
    };

    map.on('load', () => {
      setMapReady(true);
      syncMarketplaceMarkers(map, pointsRef.current, handleMarkerSelect, htmlMarkersRef, styles);
      syncHeatmapScaleVisibility();
      refreshHeatmap();
    });

    map.on('zoom', syncHeatmapScaleVisibility);
    const onZoomEnd = () => {
      syncHeatmapScaleVisibility();
      refreshHeatmap();
    };
    map.on('zoomend', onZoomEnd);

    return () => {
      heatmapSyncGenerationRef.current += 1;
      map.off('zoom', syncHeatmapScaleVisibility);
      map.off('zoomend', onZoomEnd);
      removeHeatmapLayer(map);
      removeMarketplaceMarkers(htmlMarkersRef);
      setMapReady(false);
      map.remove();
      mapRef.current = null;
    };
  }, [loadEvuaHeatmap, handleMarkerSelect, showLookingHeatmap, requestHeatmapSync]);

  useEffect(() => {
    const map = mapRef.current;
    if (!loadEvuaHeatmap || !mapReady || !map) return;
    syncMarketplaceMarkers(map, points, handleMarkerSelect, htmlMarkersRef, styles);
  }, [loadEvuaHeatmap, mapReady, points, handleMarkerSelect]);

  useEffect(() => {
    const map = mapRef.current;
    if (!mapReady || !map || !showLookingHeatmap || !loadEvuaHeatmap) {
      if (mapReady && map) removeHeatmapLayer(map);
      return;
    }
    requestHeatmapSync(map, evuaStations);
  }, [evuaStations, showLookingHeatmap, loadEvuaHeatmap, mapReady, requestHeatmapSync]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !selectedItem) return undefined;

    const onMapClick = () => {
      setSelectedItem(null);
    };

    map.on('click', onMapClick);
    return () => {
      map.off('click', onMapClick);
    };
  }, [selectedItem]);

  useEffect(() => {
    if (!paymentReturnLocationId || items.length === 0) return;
    const item = items.find(row => String(row.id) === String(paymentReturnLocationId));
    if (item) setSelectedItem(item);
  }, [paymentReturnLocationId, items]);

  useEffect(() => {
    if (!paymentReturnId || !isMarketplaceApiConfigured()) return undefined;

    let cancelled = false;
    setRequestLoading(true);
    setPaymentError('');

    pollPaymentUntilDone(paymentReturnId, paymentReturnLocationId)
      .then(() => {
        if (!cancelled) onPaymentReturnHandled?.();
      })
      .catch(() => {
        if (!cancelled) setPaymentError(t('marketplacePayFailed'));
      })
      .finally(() => {
        if (!cancelled) setRequestLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [paymentReturnId, paymentReturnLocationId, onPaymentReturnHandled, pollPaymentUntilDone, t]);

  const handleRequestInfo = async () => {
    if (!selectedItem || requestLoading) return;
    setRequestLoading(true);
    setPaymentError('');

    const storedPaymentId = getStoredMarketplacePaymentId(selectedItem.id);
    if (storedPaymentId) {
      try {
        const unlocked = await resolveOwnerInfoFromPayment(storedPaymentId, selectedItem.id);
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
      setPaymentError(t('marketplacePayFailed'));
    } catch {
      setPaymentError(t('marketplacePayFailed'));
    } finally {
      setRequestLoading(false);
    }
  };

  const handleSkipPaymentTest = async () => {
    if (!selectedItem || requestLoading) return;
    setRequestLoading(true);
    setPaymentError('');
    try {
      const status = await createMarketplaceTestPayment(selectedItem.id, {
        clientUiId: getClientId(),
      });
      if (status?.payment_id) {
        const unlocked = await resolveOwnerInfoFromPayment(status.payment_id, selectedItem.id);
        if (!unlocked) {
          setPaymentError(t('marketplacePayFailed'));
        }
        return;
      }
      setPaymentError(t('marketplacePayFailed'));
    } catch {
      setPaymentError(t('marketplacePayFailed'));
    } finally {
      setRequestLoading(false);
    }
  };

  const showLocalTestPayment = isMarketplaceLocalTestPaymentEnabled();

  if (!isMarketplaceApiConfigured()) {
    return null;
  }

  return (
    <section
      className={`${styles.root}${hideHeader ? ` ${styles.rootEmbedded}` : ''}`}
      aria-labelledby={hideHeader ? undefined : 'marketplace-map-title'}
    >
      {hideHeader ? null : (
        <>
          <h2 id="marketplace-map-title" className={styles.title}>
            {t('marketplaceTitle')}
          </h2>
          <p className={styles.subtitle}>{t('marketplaceMapHint')}</p>
        </>
      )}

      {loading ? <p className={styles.status}>{t('marketplaceLeadFormMapLoading')}</p> : null}
      {error ? <p className={styles.error}>{error}</p> : null}

      <div className={styles.mapWrap}>
        <div ref={mapContainerRef} className={styles.map} aria-label={t('marketplaceMapAria')} />

        {showHeatmapLegend ? (
          <div className={styles.heatmapLegend} aria-hidden>
            <span className={styles.heatmapLegendTitle}>{t('marketplaceHeatmapLegendTitle')}</span>
            <div className={styles.heatmapLegendScale}>
              <span className={styles.heatmapLegendLow}>{t('marketplaceHeatmapLegendLow')}</span>
              <span className={styles.heatmapLegendBar} />
              <span className={styles.heatmapLegendHigh}>{t('marketplaceHeatmapLegendHigh')}</span>
            </div>
          </div>
        ) : null}

        {selectedItem ? (
          <div
            className={styles.detailPanel}
            role="dialog"
            aria-label={t('marketplaceDetailTitle')}
            onClick={e => e.stopPropagation()}
          >
            <div className={styles.detailHeader}>
              <h3 className={styles.detailTitle}>{t('marketplaceDetailTitle')}</h3>
              <button
                type="button"
                className={styles.detailCloseBtn}
                onClick={() => setSelectedItem(null)}
                aria-label={t('marketplaceClose')}
              >
                ×
              </button>
            </div>

            <MarketplaceDetailsBody item={selectedItem} t={t} language={locale} variant="map" />

            <p className={styles.viewCount}>
              {t('marketplaceViewedTimes', { count: selectedItem.view_count || 0 })}
            </p>

            {paymentError ? <p className={styles.paymentError}>{paymentError}</p> : null}

            <button
              type="button"
              className={styles.requestInfoBtn}
              onClick={handleRequestInfo}
              disabled={requestLoading}
            >
              {requestLoading ? t('marketplaceLeadFormMapLoading') : t('marketplaceRequestInfo')}
            </button>
            {showLocalTestPayment ? (
              <button
                type="button"
                className={styles.payTestBtn}
                onClick={handleSkipPaymentTest}
                disabled={requestLoading}
              >
                {t('marketplacePayTestSkip')}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>

      {!loading && !error && items.length === 0 ? (
        <p className={styles.empty}>{t('marketplaceEmpty')}</p>
      ) : null}

      <MarketplaceModal
        open={ownerModalOpen}
        onClose={() => setOwnerModalOpen(false)}
        ariaLabel={t('marketplaceOwnerInfoTitle')}
      >
        <div className={styles.contactModal}>
          <h3 className={styles.contactTitle}>{t('marketplaceOwnerInfoTitle')}</h3>
          <OwnerInfoBody ownerInfo={ownerInfo} t={t} />
        </div>
      </MarketplaceModal>
    </section>
  );
}
