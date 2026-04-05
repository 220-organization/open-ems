/** Simulation + geometry for Power flow (no React). */

export const FLOW_DOT_MOTION_DUR = '2.2s';
export const LINE_EDGE_INSET = 44;

export const BINANCE_MINER_URL =
  'https://pool.binance.com/en/statistics?urlParams=k0L2WD9yFZlqcgCbBtRfiu040xT4UPvxRgFKVq0hr4k08962';
export const SITE_220KM_HOME = 'https://220-km.com/';
export const EV_LIST_URL = 'https://220-km.com/list';

const KYIV_PV_START_HOUR = [8, 7.5, 7, 6, 5.5, 5, 5, 5.5, 6, 6.5, 7.5, 8];
const KYIV_PV_END_HOUR = [16, 17, 18.5, 19.5, 20.5, 21.5, 21, 20, 18.5, 17, 16, 15.5];

export function getKyivWallClock(date) {
  const dtf = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Europe/Kiev',
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: 'numeric',
    minute: 'numeric',
    second: 'numeric',
    hour12: false,
  });
  const parts = dtf.formatToParts(date);
  const map = {};
  for (const p of parts) {
    if (p.type !== 'literal') map[p.type] = p.value;
  }
  const month = Number(map.month) - 1;
  const hour = Number(map.hour);
  const minute = Number(map.minute);
  const second = Number(map.second);
  const hourFloat = hour + minute / 60 + second / 3600;
  return { month, hour, hourFloat };
}

export function isKyivPvHours(month, hourFloat) {
  const start = KYIV_PV_START_HOUR[month] ?? 7;
  const end = KYIV_PV_END_HOUR[month] ?? 18;
  return hourFloat >= start && hourFloat < end;
}

export function formatPower(watts, t, bcp47) {
  if (watts == null || !Number.isFinite(watts)) return '—';
  const nf = new Intl.NumberFormat(bcp47, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (watts >= 1_000_000) return `${nf.format(watts / 1_000_000)}\u00a0${t('unitMW')}`;
  return `${nf.format(watts / 1000)}\u00a0${t('unitKW')}`;
}

/** Same scaling as formatPower but digits only (no MW/kW suffix) — compact header / EV hints. */
export function formatPowerValueOnly(watts, bcp47) {
  if (watts == null || !Number.isFinite(watts)) return '—';
  const nf = new Intl.NumberFormat(bcp47, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (watts >= 1_000_000) return nf.format(watts / 1_000_000);
  return nf.format(watts / 1000);
}

export function formatUsdt(value, bcp47) {
  if (value == null || !Number.isFinite(value)) return null;
  const nf = new Intl.NumberFormat(bcp47, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `+${nf.format(Math.max(0, value))}`;
}

export function lineEndInset(x1, y1, x2, y2, inset) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.hypot(dx, dy) || 1;
  const clamped = Math.min(inset, len * 0.42);
  const ux = dx / len;
  const uy = dy / len;
  return { x: x2 - ux * clamped, y: y2 - uy * clamped };
}

export function lineCenteredBetween(nodeX, nodeY, hubX, hubY, inset = LINE_EDGE_INSET) {
  const dx = hubX - nodeX;
  const dy = hubY - nodeY;
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len;
  const uy = dy / len;
  const midX = (nodeX + hubX) / 2;
  const midY = (nodeY + hubY) / 2;
  const halfLen = Math.min(inset, len * 0.45) / 2;
  return {
    start: { x: midX - ux * halfLen, y: midY - uy * halfLen },
    end: { x: midX + ux * halfLen, y: midY + uy * halfLen },
  };
}

export function flowMotionPath(x1, y1, x2, y2) {
  const { x, y } = lineEndInset(x1, y1, x2, y2, 0);
  return `M ${x1} ${y1} L ${x} ${y}`;
}

/**
 * Distance from graph edge to outer node center (px). Wider on narrow containers so
 * tiles stay inside the square; must match CSS --pf-graph-anchor-pct on .pf-graph.
 */
export function edgeInsetPx(containerW) {
  const w = Math.max(containerW, 1);
  if (w >= 560) return 34;
  const t = Math.max(0, Math.min(1, (560 - w) / 220));
  return 34 + t * 44;
}

export function computeWideGeometry(containerW) {
  const w = Math.max(containerW, 1);
  const insetPx = edgeInsetPx(w);
  const toVB = (px) => (400 * px) / w;
  const cx = 200;
  const cy = 200;
  const nwWide = toVB(insetPx);

  const solar = { x: nwWide, y: nwWide };
  const grid = { x: nwWide, y: cy };
  const load = { x: nwWide, y: 400 - nwWide };
  const ess = { x: 400 - nwWide, y: nwWide };
  const miner = { x: 400 - nwWide, y: cy };
  const consumption = { x: 400 - nwWide, y: 400 - nwWide };

  const solarLine = lineCenteredBetween(solar.x, solar.y, cx, cy);
  const gridLineRaw = lineCenteredBetween(grid.x, grid.y, cx, cy);
  const gridLineSellingRaw = lineCenteredBetween(cx, cy, grid.x, grid.y);
  const gridLine = {
    start: { x: gridLineRaw.start.x, y: cy },
    end: { x: gridLineRaw.end.x, y: cy },
  };
  const gridLineSelling = {
    start: { x: gridLineSellingRaw.start.x, y: cy },
    end: { x: gridLineSellingRaw.end.x, y: cy },
  };
  const loadLine = lineCenteredBetween(cx, cy, load.x, load.y);
  const essLine = lineCenteredBetween(ess.x, ess.y, cx, cy);
  const essLineCharging = lineCenteredBetween(cx, cy, ess.x, ess.y);
  const minerLine = lineCenteredBetween(cx, cy, miner.x, miner.y);
  const consumptionLine = lineCenteredBetween(cx, cy, consumption.x, consumption.y);

  return {
    solarLine,
    gridLine,
    gridLineSelling,
    loadLine,
    essLine,
    essLineCharging,
    minerLine,
    consumptionLine,
  };
}

export function computeSimulatedSources(consumptionMw, liveMinerW) {
  const now = new Date();
  const { month, hour, hourFloat } = getKyivWallClock(now);
  const consumptionW =
    consumptionMw != null && Number.isFinite(consumptionMw) ? consumptionMw * 1e6 : 0;
  const useLiveMiner =
    liveMinerW != null && Number.isFinite(liveMinerW) && liveMinerW >= 0 ? liveMinerW : null;

  const isPvHours = isKyivPvHours(month, hourFloat);
  const essDischarging = hour >= 18 && hour <= 21;

  let solarW = 0;
  let essW = 0;
  let gridW = 0;
  let minerW = 0;

  const MAX_ESS_POWER_W = 100000;
  const MAX_SOLAR_POWER_W = 20000;
  const MIN_SOLAR_TO_ESS_PCT = 0.07;
  const MIN_SOLAR_TO_MINER_PCT = 0.04;
  const NIGHT_GRID_TO_ESS_W = 200000;
  const MIN_GRID_TO_EV_PCT = 0.3;

  const nightGridCharge = hour >= 1 && hour < 3;

  if (nightGridCharge) {
    essW = -NIGHT_GRID_TO_ESS_W;
    gridW = NIGHT_GRID_TO_ESS_W + Math.max(0, consumptionW);
  } else if (consumptionW > 0 || isPvHours) {
    if (isPvHours) {
      const solarPeak = Math.min((consumptionW || 50000) * 1.3, MAX_SOLAR_POWER_W);
      const h = hourFloat;
      const noon = 13;
      const spread = 5;
      solarW = Math.min(
        MAX_SOLAR_POWER_W,
        Math.max(0, solarPeak * Math.exp(-(((h - noon) / spread) ** 2))),
      );
      minerW = solarW * MIN_SOLAR_TO_MINER_PCT;
    }
    if (useLiveMiner != null) minerW = useLiveMiner;

    const solarAfterMiner = solarW - minerW;

    if (consumptionW > 0) {
      if (essDischarging) {
        const essSupply = Math.min(consumptionW * 0.3, MAX_ESS_POWER_W);
        essW = essSupply;
        gridW = Math.max(0, consumptionW - solarAfterMiner - essSupply);
      } else if (isPvHours && solarW > 0) {
        const minEssCharge = Math.min(solarW * MIN_SOLAR_TO_ESS_PCT, MAX_ESS_POWER_W);
        const solarForEvAndEss = solarAfterMiner - minEssCharge;

        if (solarForEvAndEss >= consumptionW) {
          const excess = solarForEvAndEss - consumptionW;
          const additionalToEss = Math.min(excess, MAX_ESS_POWER_W - minEssCharge);
          essW = -(minEssCharge + additionalToEss);
          gridW = -Math.max(0, excess - additionalToEss);
        } else {
          essW = -minEssCharge;
          gridW = consumptionW - solarForEvAndEss;
        }
      } else {
        gridW = consumptionW - solarAfterMiner;
      }
    }

    if (consumptionW > 0) {
      const minGridToEvW = consumptionW * MIN_GRID_TO_EV_PCT;
      if (gridW < minGridToEvW) {
        const diff = minGridToEvW - gridW;
        gridW = minGridToEvW;
        solarW = Math.max(0, solarW - diff);
        if (useLiveMiner == null) minerW = solarW * MIN_SOLAR_TO_MINER_PCT;
      }
    }
  }

  if (useLiveMiner != null) minerW = useLiveMiner;

  return {
    solarW,
    gridW,
    essW,
    minerW,
    essCharging: essW < 0,
    essDischarging: essW > 0,
    consumptionW,
  };
}
