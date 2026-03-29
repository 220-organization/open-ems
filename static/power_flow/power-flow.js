/**
 * Power flow visualization — same public data and simulation idea as B2B FlowGraph (graphView=1).
 * Fetches via same-origin proxy: /api/b2b/* → https://220-km.com/b2b/public/*
 */

import { initI18n, t, getBcp47Locale } from './i18n.js';

const FLOW_DOT_MOTION_DUR = '2.2s';
const LINE_EDGE_INSET = 44;

const BINANCE_MINER_URL =
  'https://pool.binance.com/en/statistics?urlParams=k0L2WD9yFZlqcgCbBtRfiu040xT4UPvxRgFKVq0hr4k08962';
const WIND_DOC_URL = 'https://drive.google.com/file/d/102AcXuk6Cz4Zn7EMfHhPO2HnkMo7_2nc/view?usp=sharing';
const EV_LIST_URL = 'https://220-km.com/list';

const KYIV_PV_START_HOUR = [8, 7.5, 7, 6, 5.5, 5, 5, 5.5, 6, 6.5, 7.5, 8];
const KYIV_PV_END_HOUR = [16, 17, 18.5, 19.5, 20.5, 21.5, 21, 20, 18.5, 17, 16, 15.5];

function getKyivWallClock(date) {
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

function isKyivPvHours(month, hourFloat) {
  const start = KYIV_PV_START_HOUR[month] ?? 7;
  const end = KYIV_PV_END_HOUR[month] ?? 18;
  return hourFloat >= start && hourFloat < end;
}

function formatPower(watts) {
  if (watts == null || !Number.isFinite(watts)) return '—';
  const nf = new Intl.NumberFormat(getBcp47Locale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (watts >= 1_000_000) return `${nf.format(watts / 1_000_000)}\u00a0${t('unitMW')}`;
  return `${nf.format(watts / 1000)}\u00a0${t('unitKW')}`;
}

function formatUsdt(value) {
  if (value == null || !Number.isFinite(value)) return null;
  const nf = new Intl.NumberFormat(getBcp47Locale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `+${nf.format(Math.max(0, value))}`;
}

function lineEndInset(x1, y1, x2, y2, inset) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.hypot(dx, dy) || 1;
  const clamped = Math.min(inset, len * 0.42);
  const ux = dx / len;
  const uy = dy / len;
  return { x: x2 - ux * clamped, y: y2 - uy * clamped };
}

function lineCenteredBetween(nodeX, nodeY, hubX, hubY, inset = LINE_EDGE_INSET) {
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

function flowMotionPath(x1, y1, x2, y2) {
  const { x, y } = lineEndInset(x1, y1, x2, y2, 0);
  return `M ${x1} ${y1} L ${x} ${y}`;
}

function computeWideGeometry(containerW) {
  const w = Math.max(containerW, 1);
  const toVB = px => (400 * px) / w;
  const cx = 200;
  const cy = 200;
  const nwWide = toVB(34);

  const solar = { x: nwWide, y: nwWide };
  const grid = { x: nwWide, y: cy };
  const wind = { x: nwWide, y: 400 - nwWide };
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
  const windLine = lineCenteredBetween(wind.x, wind.y, cx, cy);
  const essLine = lineCenteredBetween(ess.x, ess.y, cx, cy);
  const essLineCharging = lineCenteredBetween(cx, cy, ess.x, ess.y);
  const minerLine = lineCenteredBetween(cx, cy, miner.x, miner.y);
  const consumptionLine = lineCenteredBetween(cx, cy, consumption.x, consumption.y);

  return {
    solarLine,
    gridLine,
    gridLineSelling,
    windLine,
    essLine,
    essLineCharging,
    minerLine,
    consumptionLine,
  };
}

function computeSimulatedSources(consumptionMw, liveMinerW) {
  const now = new Date();
  const { month, hour, hourFloat } = getKyivWallClock(now);
  const consumptionW = consumptionMw != null && Number.isFinite(consumptionMw) ? consumptionMw * 1e6 : 0;
  const useLiveMiner = liveMinerW != null && Number.isFinite(liveMinerW) && liveMinerW >= 0 ? liveMinerW : null;

  const isPvHours = isKyivPvHours(month, hourFloat);
  const essDischarging = hour >= 18 && hour <= 21;
  const essChargingSlot = hour >= 11 && hour <= 16 && isPvHours;

  let solarW = 0;
  let windW = 0;
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
    windW,
    gridW,
    essW,
    minerW,
    essCharging: essW < 0,
    essDischarging: essW > 0,
    consumptionW,
  };
}

function setLine(el, x1, y1, x2, y2, active) {
  if (!el) return;
  el.setAttribute('x1', x1);
  el.setAttribute('y1', y1);
  el.setAttribute('x2', x2);
  el.setAttribute('y2', y2);
  el.dataset.active = active ? 'true' : 'false';
}

function setDot(group, show, pathD) {
  if (!group) return;
  group.style.display = show ? '' : 'none';
  const motion = group.querySelector('animateMotion');
  if (motion && pathD) motion.setAttribute('path', pathD);
}

let realtimePower = null;
let minerSnap = null;
let loadError = '';
let stationFilter = '';

function buildNodes() {
  const host = document.getElementById('pf-nodes');
  if (!host) return;
  host.innerHTML = `
    <div class="pf-node" data-pos="left-top" id="pf-node-solar" data-active="false">
      <span class="pf-node-icon" aria-hidden>☀️</span>
      <span class="pf-node-label">${t('nodeSolar')}</span>
      <span class="pf-node-value" id="pf-val-solar">—</span>
    </div>
    <button type="button" class="pf-node" data-pos="left-center" id="pf-node-grid" data-active="false">
      <span class="pf-node-icon" aria-hidden>⚡</span>
      <span class="pf-node-label">${t('nodeGrid')}</span>
      <span class="pf-node-value" id="pf-val-grid">—</span>
      <span class="pf-ess-status" id="pf-grid-selling" hidden>${t('gridSelling')}</span>
    </button>
    <a class="pf-node" data-pos="left-bottom" id="pf-node-wind" href="${WIND_DOC_URL}" target="_blank" rel="noopener noreferrer" data-active="false">
      <span class="pf-node-icon" aria-hidden>💨</span>
      <span class="pf-node-label">${t('nodeWind')}</span>
      <span class="pf-node-value" id="pf-val-wind">—</span>
    </a>
    <div class="pf-hub" id="pf-hub" data-active="false">
      <span class="pf-hub-wordmark">220-km.com</span>
      <span class="pf-hub-label">${t('hubLabel')}</span>
    </div>
    <button type="button" class="pf-node" data-pos="right-top" id="pf-node-ess" data-active="false">
      <span class="pf-node-icon" id="pf-ess-icon" aria-hidden>🔋</span>
      <span class="pf-node-label">${t('nodeEss')}</span>
      <span class="pf-node-value" id="pf-val-ess">—</span>
      <span class="pf-ess-status" id="pf-ess-ch" hidden>${t('essCharge')}</span>
      <span class="pf-ess-status" id="pf-ess-disch" hidden>${t('essDischarge')}</span>
    </button>
    <a class="pf-node" data-pos="right-center" id="pf-node-miner" href="${BINANCE_MINER_URL}" target="_blank" rel="noopener noreferrer" data-active="false">
      <span class="pf-node-icon" aria-hidden>💠</span>
      <span class="pf-node-label" id="pf-miner-label">${t('nodeMiner')}</span>
      <span class="pf-node-value" id="pf-val-miner">—</span>
      <div class="pf-node-sub" id="pf-miner-usdt"></div>
      <div class="pf-node-meta" id="pf-miner-tariff"></div>
    </a>
    <a class="pf-node" data-pos="right-bottom" id="pf-node-ev" href="${EV_LIST_URL}" target="_blank" rel="noopener noreferrer" data-active="false">
      <span class="pf-node-icon" aria-hidden>🚗</span>
      <span class="pf-node-label">${t('nodeEv')}</span>
      <span class="pf-node-value" id="pf-val-ev">—</span>
    </a>
  `;
}

function buildSvgLines(svgNS) {
  const lines = document.getElementById('pf-lines');
  const dots = document.getElementById('pf-dots');
  if (!lines || !dots) return;
  lines.innerHTML = '';
  dots.innerHTML = '';

  const segments = [
    ['solar', 'pf-line-solar'],
    ['grid', 'pf-line-grid'],
    ['wind', 'pf-line-wind'],
    ['ess', 'pf-line-ess'],
    ['miner', 'pf-line-miner'],
    ['cons', 'pf-line-cons'],
  ];

  for (const [, lineId] of segments) {
    const line = document.createElementNS(svgNS, 'line');
    line.setAttribute('class', 'pf-line');
    line.setAttribute('id', lineId);
    lines.appendChild(line);
  }

  for (const [key] of segments) {
    const g = document.createElementNS(svgNS, 'g');
    g.setAttribute('id', `pf-dot-${key}`);
    g.style.display = 'none';
    const circle = document.createElementNS(svgNS, 'circle');
    circle.setAttribute('r', '5.8');
    circle.setAttribute('fill', 'url(#pf-flow-dot-grad)');
    circle.setAttribute('class', 'pf-flow-dot');
    const motion = document.createElementNS(svgNS, 'animateMotion');
    motion.setAttribute('dur', FLOW_DOT_MOTION_DUR);
    motion.setAttribute('repeatCount', 'indefinite');
    motion.setAttribute('calcMode', 'spline');
    motion.setAttribute('keyTimes', '0;1');
    motion.setAttribute('keySplines', '0.45 0 0.55 1');
    const fade = document.createElementNS(svgNS, 'animate');
    fade.setAttribute('attributeName', 'opacity');
    fade.setAttribute('values', '0.98;0.98;0');
    fade.setAttribute('keyTimes', '0;0.82;1');
    fade.setAttribute('dur', FLOW_DOT_MOTION_DUR);
    fade.setAttribute('repeatCount', 'indefinite');
    circle.appendChild(motion);
    circle.appendChild(fade);
    g.appendChild(circle);
    dots.appendChild(g);
  }
}

function render() {
  const graph = document.getElementById('pf-graph');
  const errEl = document.getElementById('pf-error');
  errEl.hidden = !loadError;
  errEl.textContent = loadError;

  const consumptionMw = realtimePower?.powerMw ?? 0;
  const liveMinerW =
    minerSnap?.configured && minerSnap.powerW != null && Number.isFinite(minerSnap.powerW)
      ? Math.max(0, minerSnap.powerW)
      : null;

  const sim = computeSimulatedSources(consumptionMw, liveMinerW);
  const { solarW, windW, gridW, essW, minerW, essCharging, essDischarging, consumptionW } = sim;
  const gridSelling = gridW < 0;
  const hasFlow = consumptionW > 0 || minerW > 0 || essW !== 0 || gridW !== 0;

  const geom = computeWideGeometry(graph.offsetWidth || 400);

  const lineSolar = document.getElementById('pf-line-solar');
  const lineGrid = document.getElementById('pf-line-grid');
  const lineWind = document.getElementById('pf-line-wind');
  const lineEss = document.getElementById('pf-line-ess');
  const lineMiner = document.getElementById('pf-line-miner');
  const lineCons = document.getElementById('pf-line-cons');

  setLine(lineSolar, geom.solarLine.start.x, geom.solarLine.start.y, geom.solarLine.end.x, geom.solarLine.end.y, hasFlow && solarW > 0);
  setDot(
    document.getElementById('pf-dot-solar'),
    hasFlow && solarW > 0,
    flowMotionPath(geom.solarLine.start.x, geom.solarLine.start.y, geom.solarLine.end.x, geom.solarLine.end.y),
  );

  const gBuy = geom.gridLine;
  const gSell = geom.gridLineSelling;
  if (gridSelling) {
    setLine(lineGrid, gSell.start.x, gSell.start.y, gSell.end.x, gSell.end.y, hasFlow && Math.abs(gridW) > 0);
    setDot(
      document.getElementById('pf-dot-grid'),
      hasFlow && Math.abs(gridW) > 0,
      flowMotionPath(gSell.start.x, gSell.start.y, gSell.end.x, gSell.end.y),
    );
  } else {
    setLine(lineGrid, gBuy.start.x, gBuy.start.y, gBuy.end.x, gBuy.end.y, hasFlow && Math.abs(gridW) > 0);
    setDot(
      document.getElementById('pf-dot-grid'),
      hasFlow && Math.abs(gridW) > 0,
      flowMotionPath(gBuy.start.x, gBuy.start.y, gBuy.end.x, gBuy.end.y),
    );
  }

  setLine(lineWind, geom.windLine.start.x, geom.windLine.start.y, geom.windLine.end.x, geom.windLine.end.y, hasFlow && windW > 0);
  setDot(
    document.getElementById('pf-dot-wind'),
    hasFlow && windW > 0,
    flowMotionPath(geom.windLine.start.x, geom.windLine.start.y, geom.windLine.end.x, geom.windLine.end.y),
  );

  const essActive = hasFlow && Math.abs(essW) > 0;
  if (essCharging) {
    setLine(
      lineEss,
      geom.essLineCharging.start.x,
      geom.essLineCharging.start.y,
      geom.essLineCharging.end.x,
      geom.essLineCharging.end.y,
      essActive,
    );
    setDot(
      document.getElementById('pf-dot-ess'),
      essActive,
      flowMotionPath(
        geom.essLineCharging.start.x,
        geom.essLineCharging.start.y,
        geom.essLineCharging.end.x,
        geom.essLineCharging.end.y,
      ),
    );
  } else {
    setLine(lineEss, geom.essLine.start.x, geom.essLine.start.y, geom.essLine.end.x, geom.essLine.end.y, essActive);
    setDot(
      document.getElementById('pf-dot-ess'),
      essActive,
      flowMotionPath(geom.essLine.start.x, geom.essLine.start.y, geom.essLine.end.x, geom.essLine.end.y),
    );
  }

  setLine(
    lineMiner,
    geom.minerLine.start.x,
    geom.minerLine.start.y,
    geom.minerLine.end.x,
    geom.minerLine.end.y,
    hasFlow && minerW > 0,
  );
  setDot(
    document.getElementById('pf-dot-miner'),
    hasFlow && minerW > 0,
    flowMotionPath(geom.minerLine.start.x, geom.minerLine.start.y, geom.minerLine.end.x, geom.minerLine.end.y),
  );

  setLine(
    lineCons,
    geom.consumptionLine.start.x,
    geom.consumptionLine.start.y,
    geom.consumptionLine.end.x,
    geom.consumptionLine.end.y,
    hasFlow && consumptionW > 0,
  );
  setDot(
    document.getElementById('pf-dot-cons'),
    hasFlow && consumptionW > 0,
    flowMotionPath(
      geom.consumptionLine.start.x,
      geom.consumptionLine.start.y,
      geom.consumptionLine.end.x,
      geom.consumptionLine.end.y,
    ),
  );

  const setNodeActive = (id, on) => {
    const el = document.getElementById(id);
    if (el) el.dataset.active = on ? 'true' : 'false';
  };

  setNodeActive('pf-node-solar', hasFlow && solarW > 0);
  setNodeActive('pf-node-grid', hasFlow && Math.abs(gridW) > 0);
  setNodeActive('pf-node-wind', hasFlow && windW > 0);
  setNodeActive('pf-node-ess', essActive);
  setNodeActive('pf-node-miner', hasFlow && minerW > 0);
  setNodeActive('pf-node-ev', hasFlow && consumptionW > 0);
  const hub = document.getElementById('pf-hub');
  if (hub) hub.dataset.active = hasFlow ? 'true' : 'false';

  document.getElementById('pf-val-solar').textContent = formatPower(solarW);
  const gridEl = document.getElementById('pf-val-grid');
  gridEl.textContent = gridSelling ? `↓ ${formatPower(Math.abs(gridW))}` : formatPower(gridW);
  const gs = document.getElementById('pf-grid-selling');
  if (gs) gs.hidden = !gridSelling;
  document.getElementById('pf-val-wind').textContent = formatPower(windW);
  document.getElementById('pf-val-ess').textContent = formatPower(Math.abs(essW));
  const ech = document.getElementById('pf-ess-ch');
  const edc = document.getElementById('pf-ess-disch');
  if (ech) ech.hidden = !essCharging;
  if (edc) edc.hidden = !essDischarging;
  document.getElementById('pf-ess-icon').textContent = essCharging ? '🔌' : essDischarging ? '🔋' : '🔋';

  document.getElementById('pf-val-miner').textContent = formatPower(minerW);
  const usdt = formatUsdt(minerSnap?.minedUsdtToday);
  const usdtEl = document.getElementById('pf-miner-usdt');
  usdtEl.textContent = usdt ? `${usdt} ${t('usdtSuffix')}` : '';
  const tf = minerSnap?.tariffUahPerKwh;
  const tfEl = document.getElementById('pf-miner-tariff');
  if (tf != null && Number.isFinite(tf)) {
    const nf = new Intl.NumberFormat(getBcp47Locale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    tfEl.textContent = t('tariffKwh', { value: nf.format(Math.max(0, tf)) });
  } else {
    tfEl.textContent = '';
  }

  let minerLabel = t('nodeMiner');
  if (
    minerSnap?.configured &&
    minerSnap.workersActive != null &&
    minerSnap.workersTotal != null
  ) {
    minerLabel += ` (${minerSnap.workersActive}/${minerSnap.workersTotal})`;
  }
  document.getElementById('pf-miner-label').textContent = minerLabel;

  const evBusy = realtimePower == null && loadError === '';
  document.getElementById('pf-val-ev').textContent = evBusy ? '…' : formatPower(consumptionW);
}

async function fetchRealtime() {
  const q = stationFilter ? `?station=${encodeURIComponent(stationFilter)}` : '';
  const r = await fetch(`/api/b2b/realtime-power${q}`);
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  realtimePower = await r.json();
}

async function fetchMiner() {
  const r = await fetch('/api/b2b/miner-power');
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  minerSnap = await r.json();
}

async function refreshRealtime() {
  try {
    await fetchRealtime();
    loadError = '';
  } catch (e) {
    loadError = e instanceof Error ? e.message : String(e);
  }
  render();
}

async function refreshMiner() {
  try {
    await fetchMiner();
  } catch {
    /* keep previous minerSnap */
  }
  render();
}

const INVERTER_STORAGE = 'pf-deye-inverter';

function refreshInverterOptionNone() {
  const sel = document.getElementById('pf-inverter');
  if (!sel || !sel.options.length) return;
  const first = sel.options[0];
  if (first && first.value === '') first.textContent = t('inverterOptionNone');
}

async function setupInverterSelect() {
  const sel = document.getElementById('pf-inverter');
  if (!sel) return;

  try {
    const r = await fetch('/api/deye/inverters');
    let data = {};
    try {
      data = await r.json();
    } catch {
      data = {};
    }

    sel.innerHTML = '';
    const none = document.createElement('option');
    none.value = '';
    none.textContent = t('inverterOptionNone');
    sel.appendChild(none);

    if (!r.ok) {
      const err = document.createElement('option');
      err.value = '';
      err.disabled = true;
      err.textContent = t('inverterLoadError');
      sel.appendChild(err);
      return;
    }

    if (!data.configured) {
      const opt = document.createElement('option');
      opt.value = '';
      opt.disabled = true;
      opt.textContent = t('inverterNotConfigured');
      sel.appendChild(opt);
    } else {
      for (const row of data.items || []) {
        const o = document.createElement('option');
        o.value = row.deviceSn;
        o.textContent = row.label || row.deviceSn;
        sel.appendChild(o);
      }
    }

    const params = new URLSearchParams(window.location.search);
    let want = params.get('inverter') || '';
    if (!want) {
      try {
        want = localStorage.getItem(INVERTER_STORAGE) || '';
      } catch {
        /* ignore */
      }
    }
    if (want && [...sel.options].some((o) => o.value === want)) {
      sel.value = want;
    } else {
      sel.value = '';
    }

    sel.addEventListener('change', () => {
      const v = sel.value.trim();
      try {
        if (v) localStorage.setItem(INVERTER_STORAGE, v);
        else localStorage.removeItem(INVERTER_STORAGE);
      } catch {
        /* ignore */
      }
      const u = new URL(window.location.href);
      if (v) u.searchParams.set('inverter', v);
      else u.searchParams.delete('inverter');
      window.history.replaceState({}, '', u);
    });
  } catch {
    sel.innerHTML = '';
    const none = document.createElement('option');
    none.value = '';
    none.textContent = t('inverterOptionNone');
    sel.appendChild(none);
    const err = document.createElement('option');
    err.value = '';
    err.disabled = true;
    err.textContent = t('inverterLoadError');
    sel.appendChild(err);
  }
}

function init() {
  if (!document.getElementById('pf-nodes') || !document.getElementById('pf-lines')) {
    console.error('power-flow: required DOM missing');
    return;
  }
  const svgNS = 'http://www.w3.org/2000/svg';
  buildNodes();
  buildSvgLines(svgNS);

  const params = new URLSearchParams(window.location.search);
  const stationInput = document.getElementById('pf-station');
  if (!stationInput) return;
  stationInput.value = params.get('station') || '';
  stationFilter = stationInput.value.trim();

  stationInput.addEventListener('change', () => {
    stationFilter = stationInput.value.trim();
    const u = new URL(window.location.href);
    if (stationFilter) u.searchParams.set('station', stationFilter);
    else u.searchParams.delete('station');
    window.history.replaceState({}, '', u);
    refreshRealtime();
  });

  window.addEventListener('resize', () => render());
  window.addEventListener('load', () => render());

  requestAnimationFrame(() => render());

  refreshRealtime();
  refreshMiner();
  setInterval(refreshRealtime, 5000);
  setInterval(refreshMiner, 30_000);
  setInterval(() => render(), 60_000);
}

async function boot() {
  await initI18n({
    onLocaleChange: () => {
      buildNodes();
      render();
      refreshInverterOptionNone();
    },
  });
  init();
  await setupInverterSelect();
}

boot().catch((err) => {
  console.error('power-flow: boot failed', err);
});
