import { useState } from 'react';
import { formatPower } from './powerFlowEngine';
import { useSolarInsolationHourly } from './hooks/useSolarInsolationHourly';
import SolarInsolationDayGraph from './SolarInsolationDayGraph';
import './solarNodePopup.css';

const FONT_STACK_PERCENT_SAFE =
  'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Helvetica, Arial, sans-serif';

function formatInsolationPct(value) {
  if (value == null || !Number.isFinite(Number(value))) return '—';
  return (
    <>
      {Math.round(Number(value))}
      <span style={{ fontFamily: FONT_STACK_PERCENT_SAFE }}>{' %'}</span>
    </>
  );
}

export default function SolarNodePopupContent({
  deviceSn,
  solarForecast,
  solarPowerW,
  solarForecastIconChar,
  solarForecastIconAria,
  lcoeLine,
  bcp47,
  evOnlyGraphLoading,
  t,
}) {
  const [selectedDay, setSelectedDay] = useState('today');
  const { todayHourlyInsolation, tomorrowHourlyInsolation, loading: hourlyLoading } =
    useSolarInsolationHourly(deviceSn);
  const hourlyInsolation = selectedDay === 'tomorrow' ? tomorrowHourlyInsolation : todayHourlyInsolation;
  const solarFlowActive = solarPowerW != null && solarPowerW > 0;
  const todayPct = solarForecast?.todayPct;
  const tomorrowPct = solarForecast?.tomorrowPct;
  const forecastLoading = Boolean(solarForecast?.loading);

  return (
    <div className={`pf-node pf-node-popup-tile pf-solar-popup${solarFlowActive ? ' pf-solar-popup--active' : ''}`}>
      <span className="pf-solar-popup__title">{t('nodeSolar')}</span>
      <div className="pf-solar-popup__head">
        <span
          className="pf-node-icon pf-solar-popup__icon"
          aria-hidden={!solarForecastIconAria}
          aria-label={solarForecastIconAria}
          title={solarForecastIconAria}
        >
          {solarForecastIconChar}
        </span>
        <span className={`pf-node-value pf-solar-popup__power${solarFlowActive ? ' pf-solar-popup__power--active' : ''}`}>
          {evOnlyGraphLoading ? '…' : formatPower(solarPowerW, t, bcp47)}
        </span>
      </div>

      {deviceSn ? (
        <div className="pf-solar-popup__days" role="tablist" aria-label={t('solarInsolationForecast')}>
          <button
            type="button"
            role="tab"
            aria-selected={selectedDay === 'today'}
            className={[
              'pf-solar-popup__day',
              'pf-solar-popup__day--today',
              selectedDay === 'today' ? 'pf-solar-popup__day--selected' : '',
            ]
              .filter(Boolean)
              .join(' ')}
            onClick={() => setSelectedDay('today')}
          >
            <span className="pf-solar-popup__day-label">{t('solarInsolationTodayLabel')}</span>
            <span className="pf-solar-popup__day-value">
              {forecastLoading ? '…' : formatInsolationPct(todayPct)}
            </span>
            {selectedDay === 'today' ? <span className="pf-solar-popup__day-indicator" aria-hidden /> : null}
          </button>
          <div className="pf-solar-popup__day-divider" aria-hidden />
          <button
            type="button"
            role="tab"
            aria-selected={selectedDay === 'tomorrow'}
            className={[
              'pf-solar-popup__day',
              'pf-solar-popup__day--tomorrow',
              selectedDay === 'tomorrow' ? 'pf-solar-popup__day--selected' : '',
            ]
              .filter(Boolean)
              .join(' ')}
            onClick={() => setSelectedDay('tomorrow')}
          >
            <span className="pf-solar-popup__day-label">{t('solarInsolationTomorrowLabel')}</span>
            <span className="pf-solar-popup__day-value pf-solar-popup__day-value--tomorrow">
              {forecastLoading ? '…' : formatInsolationPct(tomorrowPct)}
            </span>
            {selectedDay === 'tomorrow' ? <span className="pf-solar-popup__day-indicator" aria-hidden /> : null}
          </button>
        </div>
      ) : null}

      {deviceSn ? (
        <SolarInsolationDayGraph
          hourlyInsolation={hourlyInsolation}
          day={selectedDay}
          loading={hourlyLoading}
          t={t}
        />
      ) : solarForecast?.hintKey ? (
        <p className="pf-solar-popup__hint">{t(solarForecast.hintKey)}</p>
      ) : null}

      {lcoeLine ? (
        <div className="pf-node-meta pf-solar-popup__lcoe" title={t('lcoeSolarMetaTitle')}>
          {lcoeLine}
        </div>
      ) : null}
    </div>
  );
}
