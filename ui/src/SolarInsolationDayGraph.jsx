import { useMemo, useId } from 'react';
import './solarInsolationDayGraph.css';

const GRAPH_WIDTH = 100;
const GRAPH_HEIGHT = 34;
const BAR_GAP = 0.6;

function buildBarGeometry(hours) {
  const count = hours.length;
  if (!count) return [];
  const barWidth = (GRAPH_WIDTH - BAR_GAP * (count - 1)) / count;
  return hours.map((entry, index) => {
    const height = Math.max(1.2, (entry.levelPct / 100) * GRAPH_HEIGHT);
    const x = index * (barWidth + BAR_GAP);
    const y = GRAPH_HEIGHT - height;
    return {
      ...entry,
      x,
      y,
      width: barWidth,
      height,
    };
  });
}

export default function SolarInsolationDayGraph({ hourlyInsolation, day = 'today', loading = false, t }) {
  const gradientId = useId().replace(/:/g, '');
  const glowFilterId = `${gradientId}-glow`;
  const bars = useMemo(() => buildBarGeometry(hourlyInsolation?.hours ?? []), [hourlyInsolation?.hours]);
  const ariaLabel =
    day === 'tomorrow' ? t('solarInsolationTomorrowGraphAria') : t('solarInsolationDayGraphAria');

  return (
    <div className="solar-insolation-day-graph" aria-busy={loading}>
      <svg
        className="solar-insolation-day-graph__svg"
        viewBox={`0 0 ${GRAPH_WIDTH} ${GRAPH_HEIGHT}`}
        role="img"
        aria-label={ariaLabel}
        preserveAspectRatio="none"
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="1" x2="0" y2="0">
            <stop offset="0%" stopColor="#ff9f43" />
            <stop offset="55%" stopColor="#ffc94a" />
            <stop offset="100%" stopColor="#ffe066" />
          </linearGradient>
          <filter id={glowFilterId} x="-40%" y="-40%" width="180%" height="180%">
            <feDropShadow dx="0" dy="0" stdDeviation="1.1" floodColor="#ffe066" floodOpacity="0.95" />
          </filter>
        </defs>
        {bars.length === 0 ? (
          <rect
            className="solar-insolation-day-graph__placeholder"
            x="0"
            y={GRAPH_HEIGHT - 2}
            width={GRAPH_WIDTH}
            height="2"
            rx="1"
          />
        ) : (
          bars.map(bar => (
            <rect
              key={`insolation-bar-${day}-${bar.hour}`}
              className={[
                'solar-insolation-day-graph__bar',
                bar.isCurrent ? 'solar-insolation-day-graph__bar--current' : '',
                bar.isPast ? 'solar-insolation-day-graph__bar--past' : 'solar-insolation-day-graph__bar--future',
              ]
                .filter(Boolean)
                .join(' ')}
              x={bar.x}
              y={bar.y}
              width={bar.width}
              height={bar.height}
              rx={Math.min(bar.width / 2, 1.4)}
              fill={`url(#${gradientId})`}
              filter={bar.isCurrent ? `url(#${glowFilterId})` : undefined}
            />
          ))
        )}
      </svg>
      {bars.length > 0 ? (
        <div className="solar-insolation-day-graph__axis" aria-hidden>
          <span>6</span>
          <span>12</span>
          <span>18</span>
        </div>
      ) : null}
    </div>
  );
}
