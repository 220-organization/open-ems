import { useCallback, useEffect, useRef, useState } from 'react';
import * as maptilersdk from '@maptiler/sdk';
import '@maptiler/sdk/dist/maptiler-sdk.css';
import { v4 as uuidv4 } from 'uuid';
import {
  REGION_RADIUS_KM_DEFAULT,
  REGION_RADIUS_KM_OPTIONS,
  buildGoogleMapsPointUrl,
  formatRegionRadiusKm,
} from './messengerLinks';
import styles from './LocationMapPicker.module.css';

const MAPTILER_API_KEY = '1Lk2s9HJjoiXBR1oqw5a';
const UKRAINE_CENTER = [31.223, 49.454];
const DEFAULT_ZOOM = 6;
const MARKERS_SOURCE_ID = 'b2b-location-markers';
const MARKERS_LAYER_ID = 'b2b-location-markers-layer';
const REGION_SOURCE_ID = 'b2b-location-region';
const REGION_FILL_LAYER_ID = 'b2b-location-region-fill';
const REGION_OUTLINE_LAYER_ID = 'b2b-location-region-outline';
const REGION_CENTER_SOURCE_ID = 'b2b-location-region-center';
const REGION_CENTER_LAYER_ID = 'b2b-location-region-center-layer';

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

function locationsToGeoJson(locations) {
  return {
    type: 'FeatureCollection',
    features: (locations || []).map(loc => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [loc.lng, loc.lat] },
      properties: { id: loc.id },
    })),
  };
}

/** Square envelope around a circle — useful for bbox storage and heatmap grouping. */
function bboxFromRadiusKm(lng, lat, radiusKm) {
  const latRad = (lat * Math.PI) / 180;
  const latDelta = radiusKm / 111.32;
  const lngDelta = radiusKm / (111.32 * Math.cos(latRad));
  return [lng - lngDelta, lat - latDelta, lng + lngDelta, lat + latDelta];
}

/** Approximate geographic circle as a polygon (fixed radius in km regardless of zoom). */
function circleToPolygon(lng, lat, radiusKm, steps = 64) {
  const latRad = (lat * Math.PI) / 180;
  const lngScale = 111.32 * Math.cos(latRad);
  const ring = [];
  for (let i = 0; i <= steps; i += 1) {
    const angle = (i / steps) * 2 * Math.PI;
    const dLat = (radiusKm / 111.32) * Math.sin(angle);
    const dLng = (radiusKm / lngScale) * Math.cos(angle);
    ring.push([lng + dLng, lat + dLat]);
  }
  return {
    type: 'Polygon',
    coordinates: [ring],
  };
}

function buildRegionLocation(lng, lat, label, radiusKm) {
  return {
    id: uuidv4(),
    lng,
    lat,
    label,
    radius_km: radiusKm,
    bbox: bboxFromRadiusKm(lng, lat, radiusKm),
  };
}

function applyRadiusToRegion(loc, radiusKm) {
  if (!loc) return loc;
  return {
    ...loc,
    radius_km: radiusKm,
    bbox: bboxFromRadiusKm(loc.lng, loc.lat, radiusKm),
  };
}

function regionToGeoJson(locations) {
  const region = locations?.[0];
  if (!region || typeof region.lat !== 'number' || typeof region.lng !== 'number') {
    return { type: 'FeatureCollection', features: [] };
  }
  const radiusKm = region.radius_km ?? REGION_RADIUS_KM_DEFAULT;
  return {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        geometry: circleToPolygon(region.lng, region.lat, radiusKm),
        properties: { id: region.id },
      },
    ],
  };
}

function regionCenterToGeoJson(locations) {
  const region = locations?.[0];
  if (!region || typeof region.lat !== 'number' || typeof region.lng !== 'number') {
    return { type: 'FeatureCollection', features: [] };
  }
  return {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [region.lng, region.lat] },
        properties: { id: region.id },
      },
    ],
  };
}

function resolveGeocodeLanguage(locale) {
  const lang = String(locale || 'uk').toLowerCase();
  if (lang.startsWith('en')) return 'en';
  if (lang.startsWith('ru')) return 'ru';
  return 'uk';
}

function pickRegionFromGeocode(data, fallbackLng, fallbackLat) {
  const features = data?.features || [];
  const regionTypes = new Set(['region', 'county', 'municipality', 'joint_municipality', 'locality']);

  const regionFeature = features.find(feature => {
    const types = feature.place_type || [];
    return types.some(type => regionTypes.has(type));
  });

  if (regionFeature) {
    return {
      label: regionFeature.place_name || regionFeature.text || `${fallbackLat.toFixed(5)}, ${fallbackLng.toFixed(5)}`,
    };
  }

  const first = features[0];
  if (first) {
    const context = first.context || [];
    const regionCtx =
      [...context].reverse().find(item => String(item.id || '').startsWith('region.')) ||
      [...context].reverse().find(item => String(item.id || '').startsWith('municipality.'));
    const countryCtx = context.find(item => String(item.id || '').startsWith('country.'));
    const label = regionCtx
      ? countryCtx
        ? `${regionCtx.text}, ${countryCtx.text}`
        : regionCtx.text
      : first.place_name || `${fallbackLat.toFixed(5)}, ${fallbackLng.toFixed(5)}`;
    return { label };
  }

  return {
    label: `${fallbackLat.toFixed(5)}, ${fallbackLng.toFixed(5)}`,
  };
}

async function fetchReverseGeocode(lng, lat, language, types) {
  const typesParam = types ? `&types=${encodeURIComponent(types)}` : '';
  const res = await fetch(
    `https://api.maptiler.com/geocoding/${lng},${lat}.json?key=${MAPTILER_API_KEY}&language=${language}${typesParam}`
  );
  if (!res.ok) throw new Error('geocode failed');
  return res.json();
}

async function reverseGeocodePoint(lng, lat, language) {
  try {
    const data = await fetchReverseGeocode(lng, lat, language, null);
    const feature = data.features?.[0];
    return feature?.place_name || feature?.text || `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
  } catch {
    return `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
  }
}

async function reverseGeocodeRegion(lng, lat, language) {
  try {
    let data = await fetchReverseGeocode(lng, lat, language, 'region,municipality,county,locality');
    let picked = pickRegionFromGeocode(data, lng, lat);
    if (!picked.label) {
      data = await fetchReverseGeocode(lng, lat, language, null);
      picked = pickRegionFromGeocode(data, lng, lat);
    }
    return picked;
  } catch {
    return {
      label: `${lat.toFixed(5)}, ${lng.toFixed(5)}`,
    };
  }
}

export default function LocationMapPicker({ t, locale = 'uk', locations, onChange, selectionMode = 'point' }) {
  const mapContainerRef = useRef(null);
  const mapRef = useRef(null);
  const locationsRef = useRef(locations);
  const onChangeRef = useRef(onChange);
  const selectionModeRef = useRef(selectionMode);
  const regionRadiusKmRef = useRef(REGION_RADIUS_KM_DEFAULT);
  const [resolving, setResolving] = useState(false);
  const [regionRadiusKm, setRegionRadiusKm] = useState(REGION_RADIUS_KM_DEFAULT);

  const isRegionMode = selectionMode === 'region';

  locationsRef.current = locations;
  onChangeRef.current = onChange;
  selectionModeRef.current = selectionMode;
  regionRadiusKmRef.current = regionRadiusKm;

  const syncMapLayers = useCallback(
    nextLocations => {
      const map = mapRef.current;
      if (!map?.getSource) return;

      const markerSource = map.getSource(MARKERS_SOURCE_ID);
      if (markerSource) {
        markerSource.setData(locationsToGeoJson(isRegionMode ? [] : nextLocations));
      }

      const regionSource = map.getSource(REGION_SOURCE_ID);
      if (regionSource) {
        regionSource.setData(regionToGeoJson(isRegionMode ? nextLocations : []));
      }

      const centerSource = map.getSource(REGION_CENTER_SOURCE_ID);
      if (centerSource) {
        centerSource.setData(regionCenterToGeoJson(isRegionMode ? nextLocations : []));
      }
    },
    [isRegionMode]
  );

  const addRegionLocation = useCallback(
    async (lng, lat) => {
      setResolving(true);
      const region = await reverseGeocodeRegion(lng, lat, resolveGeocodeLanguage(locale));
      const next = [buildRegionLocation(lng, lat, region.label, regionRadiusKmRef.current)];
      onChangeRef.current(next);
      syncMapLayers(next);
      setResolving(false);
    },
    [locale, syncMapLayers]
  );

  const addPointLocation = useCallback(
    async (lng, lat) => {
      setResolving(true);
      const label = await reverseGeocodePoint(lng, lat, resolveGeocodeLanguage(locale));
      const next = [...locationsRef.current, { id: uuidv4(), lng, lat, label }];
      onChangeRef.current(next);
      syncMapLayers(next);
      setResolving(false);
    },
    [locale, syncMapLayers]
  );

  const handleRegionRadiusChange = nextRadiusKm => {
    setRegionRadiusKm(nextRadiusKm);
    if (!locationsRef.current.length) return;
    const next = [applyRadiusToRegion(locationsRef.current[0], nextRadiusKm)];
    onChangeRef.current(next);
    syncMapLayers(next);
  };

  useEffect(() => {
    if (mapRef.current || !mapContainerRef.current) return undefined;

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

    map.on('load', () => {
      map.addSource(MARKERS_SOURCE_ID, {
        type: 'geojson',
        data: locationsToGeoJson([]),
      });
      map.addLayer({
        id: MARKERS_LAYER_ID,
        type: 'circle',
        source: MARKERS_SOURCE_ID,
        paint: {
          'circle-radius': 8,
          'circle-color': '#f94caf',
          'circle-stroke-width': 2,
          'circle-stroke-color': '#ffffff',
        },
      });

      map.addSource(REGION_SOURCE_ID, {
        type: 'geojson',
        data: regionToGeoJson([]),
      });
      map.addLayer({
        id: REGION_FILL_LAYER_ID,
        type: 'fill',
        source: REGION_SOURCE_ID,
        paint: {
          'fill-color': '#f94caf',
          'fill-opacity': 0.22,
        },
      });
      map.addLayer({
        id: REGION_OUTLINE_LAYER_ID,
        type: 'line',
        source: REGION_SOURCE_ID,
        paint: {
          'line-color': '#f94caf',
          'line-width': 2,
        },
      });

      map.addSource(REGION_CENTER_SOURCE_ID, {
        type: 'geojson',
        data: regionCenterToGeoJson([]),
      });
      map.addLayer({
        id: REGION_CENTER_LAYER_ID,
        type: 'circle',
        source: REGION_CENTER_SOURCE_ID,
        paint: {
          'circle-radius': 7,
          'circle-color': '#ffffff',
          'circle-stroke-width': 3,
          'circle-stroke-color': '#f94caf',
        },
      });

      syncMapLayers(locationsRef.current);
    });

    map.on('click', e => {
      if (selectionModeRef.current === 'region') {
        addRegionLocation(e.lngLat.lng, e.lngLat.lat);
      } else {
        addPointLocation(e.lngLat.lng, e.lngLat.lat);
      }
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [addPointLocation, addRegionLocation, syncMapLayers]);

  useEffect(() => {
    syncMapLayers(locations);
  }, [locations, syncMapLayers]);

  useEffect(() => {
    if (!isRegionMode) return;
    const existingRadius = locations?.[0]?.radius_km;
    if (existingRadius != null && existingRadius !== regionRadiusKm) {
      setRegionRadiusKm(existingRadius);
    }
  }, [isRegionMode, locations]);

  const removeLocation = id => {
    const next = locations.filter(loc => loc.id !== id);
    onChange(next);
    syncMapLayers(next);
  };

  const locateMe = e => {
    e?.stopPropagation?.();
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      pos => {
        const { latitude, longitude } = pos.coords;
        mapRef.current?.flyTo({ center: [longitude, latitude], zoom: isRegionMode ? 8 : 15, duration: 1200 });
      },
      () => {},
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 60000 }
    );
  };

  const hintKey = isRegionMode ? 'marketplaceLeadFormRegionMapHint' : 'marketplaceLeadFormMapHint';
  const ariaKey = isRegionMode ? 'marketplaceLeadFormRegionMapAria' : 'marketplaceLeadFormMapAria';

  return (
    <div className={styles.root}>
      <p className={styles.hint}>{t(hintKey)}</p>
      {isRegionMode ? (
        <div className={styles.radiusFieldset}>
          <span className={styles.radiusLabel}>{t('marketplaceLeadFormRegionRadiusLabel')}</span>
          <div className={styles.radiusOptions} role="radiogroup" aria-label={t('marketplaceLeadFormRegionRadiusLabel')}>
            {REGION_RADIUS_KM_OPTIONS.map(option => (
              <button
                key={option}
                type="button"
                role="radio"
                aria-checked={regionRadiusKm === option}
                className={`${styles.radiusOptionBtn}${regionRadiusKm === option ? ` ${styles.radiusOptionBtnActive}` : ''}`}
                onClick={() => handleRegionRadiusChange(option)}
              >
                {formatRegionRadiusKm(option, t)}
              </button>
            ))}
          </div>
        </div>
      ) : null}
      <div className={styles.mapWrap}>
        <div
          ref={mapContainerRef}
          className={`${styles.map}${isRegionMode ? ` ${styles.mapRegionMode}` : ''}`}
          aria-label={t(ariaKey)}
        />
        <button type="button" className={styles.geolocateBtn} onClick={locateMe}>
          {t('marketplaceLeadFormMapGeolocate')}
        </button>
        {resolving ? <div className={styles.resolving}>{t('marketplaceLeadFormMapLoading')}</div> : null}
      </div>
      {locations.length > 0 ? (
        <ul className={styles.locationList}>
          {locations.map((loc, index) => (
            <li key={loc.id} className={styles.locationItem}>
              {isRegionMode ? null : <span className={styles.locationIndex}>{index + 1}.</span>}
              <div className={styles.locationText}>
                <span className={styles.locationLabel}>{loc.label}</span>
                {isRegionMode && loc.radius_km != null ? (
                  <span className={styles.locationRadius}>
                    {t('marketplaceLeadFormRegionRadiusLabel')}: {formatRegionRadiusKm(loc.radius_km, t)}
                  </span>
                ) : null}
                {isRegionMode ? null : (
                  <a
                    className={styles.locationMapLink}
                    href={buildGoogleMapsPointUrl(loc.lat, loc.lng)}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {buildGoogleMapsPointUrl(loc.lat, loc.lng)}
                  </a>
                )}
              </div>
              <button
                type="button"
                className={styles.removeBtn}
                onClick={() => removeLocation(loc.id)}
                aria-label={`${t('marketplaceLeadFormMapRemove')} ${isRegionMode ? loc.label : index + 1}`}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
