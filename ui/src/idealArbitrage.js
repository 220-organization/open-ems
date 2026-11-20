/**
 * Hindsight-optimal day-ahead battery schedule for the DAM chart overlay.
 *
 * Minimises Σ price · grid with self-consumption, optional export, off-grid
 * hours (grid forced to 0), SoC 10–100 %, and √0.9 round-trip efficiency.
 * Each stored kWh discharged also pays ``batteryLcoePerKwh`` (same unit as
 * prices), so a cycle is taken only when the spread covers the 10 % loss and
 * battery wear. No separate terminal wear: end-of-day SoC is valued at the
 * mean price.
 */

export const IDEAL_SOC_MIN = 10;
export const IDEAL_SOC_MAX = 100;
export const IDEAL_SOC_STEP = 0.5;
export const IDEAL_RTE = 0.9;
export const IDEAL_ETA = Math.sqrt(IDEAL_RTE);

const HOURS = 24;

function clamp(n, lo, hi) {
  return Math.min(hi, Math.max(lo, n));
}

function finiteOr(v, fallback) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function socIndexCount() {
  return Math.round((IDEAL_SOC_MAX - IDEAL_SOC_MIN) / IDEAL_SOC_STEP) + 1;
}

function socToIndex(soc) {
  const clamped = clamp(soc, IDEAL_SOC_MIN, IDEAL_SOC_MAX);
  return Math.round((clamped - IDEAL_SOC_MIN) / IDEAL_SOC_STEP);
}

function indexToSoc(i) {
  return IDEAL_SOC_MIN + i * IDEAL_SOC_STEP;
}

/**
 * AC-side kWh moved for a SoC transition (charge > 0 draws from AC, discharge > 0 supplies AC).
 * @returns {{ chargeKwh: number, dischargeKwh: number } | null}
 */
function transitionEnergy(fromSoc, toSoc, capacityKwh) {
  const dSoc = toSoc - fromSoc;
  if (Math.abs(dSoc) < 1e-9) return { chargeKwh: 0, dischargeKwh: 0 };
  if (dSoc > 0) {
    // Charge: AC → battery / eta stored
    const chargeKwh = ((dSoc / 100) * capacityKwh) / IDEAL_ETA;
    return { chargeKwh, dischargeKwh: 0 };
  }
  // Discharge: battery * eta → AC
  const dischargeKwh = (-dSoc / 100) * capacityKwh * IDEAL_ETA;
  return { chargeKwh: 0, dischargeKwh };
}

function hourCost(price, gridKwh) {
  if (price == null || !Number.isFinite(price)) return 0;
  if (!Number.isFinite(gridKwh)) return 0;
  return price * gridKwh;
}

/**
 * @param {object} input
 * @param {(number|null)[]} input.prices
 * @param {(number|null)[]} input.loadKwh
 * @param {(number|null)[]} input.pvKwh
 * @param {boolean[]} [input.offGrid]
 * @param {number} [input.startSocPercent]
 * @param {number} input.capacityKwh
 * @param {number} input.maxChargeKw
 * @param {number} input.maxDischargeKw
 * @param {boolean} [input.allowExport]
 * @param {number} [input.batteryLcoePerKwh] Wear per stored kWh discharged, same unit as prices.
 * @param {(number|null)[]} [input.actualGridKwh]
 * @returns {null | {
 *   hours: { socPercent: number, gridKwh: number, chargeKwh: number, dischargeKwh: number, unservedKwh: number }[],
 *   costNoBess: number,
 *   costIdeal: number,
 *   costActual: number|null,
 *   savingVsNoBess: number,
 *   savingVsActual: number|null,
 * }}
 */
export function computeIdealArbitrageDay(input) {
  const capacityKwh = Number(input?.capacityKwh);
  if (!Number.isFinite(capacityKwh) || capacityKwh <= 0) return null;

  const maxChargeKw = Math.max(0, finiteOr(input.maxChargeKw, 0));
  const maxDischargeKw = Math.max(0, finiteOr(input.maxDischargeKw, 0));
  if (maxChargeKw <= 0 && maxDischargeKw <= 0) return null;

  const allowExport = input.allowExport !== false;
  const batteryLcoePerKwh = Math.max(0, finiteOr(input.batteryLcoePerKwh, 0));
  const nStates = socIndexCount();
  const startSoc = finiteOr(input.startSocPercent, 50);
  const startIdx = socToIndex(startSoc);

  const prices = Array.from({ length: HOURS }, (_, i) => {
    const p = input.prices?.[i];
    return p != null && Number.isFinite(Number(p)) ? Number(p) : null;
  });
  const load = Array.from({ length: HOURS }, (_, i) =>
    Math.max(0, finiteOr(input.loadKwh?.[i], 0)),
  );
  const pv = Array.from({ length: HOURS }, (_, i) =>
    Math.max(0, finiteOr(input.pvKwh?.[i], 0)),
  );
  const off = Array.from({ length: HOURS }, (_, i) =>
    Boolean(input.offGrid?.[i]),
  );

  // DP: dp[h][s] = min cost from hour h with SoC index s through end of day
  // prev[h][s] = next SoC index chosen at hour h from state s
  const INF = 1e15;
  // Prefer covering off-grid load/surplus with the battery; unserved itself is not billed.
  const UNSERVED_PENALTY = 1e6;
  const priced = prices.filter((p) => p != null && Number.isFinite(p));
  const meanPrice = priced.length
    ? priced.reduce((a, b) => a + b, 0) / priced.length
    : 0;
  const dp = Array.from({ length: HOURS + 1 }, () =>
    new Float64Array(nStates).fill(INF),
  );
  const nextIdx = Array.from({ length: HOURS }, () =>
    new Int16Array(nStates).fill(-1),
  );
  // Soft terminal value so a flat price does not empty the pack (no free discharge).
  for (let s = 0; s < nStates; s++) {
    const usableAc =
      ((indexToSoc(s) - IDEAL_SOC_MIN) / 100) * capacityKwh * IDEAL_ETA;
    dp[HOURS][s] = -meanPrice * usableAc;
  }

  for (let h = HOURS - 1; h >= 0; h--) {
    const price = prices[h];
    const loadH = load[h];
    const pvH = pv[h];
    const offH = off[h];
    for (let s = 0; s < nStates; s++) {
      const fromSoc = indexToSoc(s);
      let best = INF;
      let bestTo = -1;
      let bestMoved = INF;
      for (let t = 0; t < nStates; t++) {
        const toSoc = indexToSoc(t);
        const moved = transitionEnergy(fromSoc, toSoc, capacityKwh);
        if (!moved) continue;
        const { chargeKwh, dischargeKwh } = moved;
        if (chargeKwh > maxChargeKw + 1e-9) continue;
        if (dischargeKwh > maxDischargeKw + 1e-9) continue;

        let grid = loadH - pvH + chargeKwh - dischargeKwh;
        let unserved = 0;
        if (offH) {
          // Must balance on battery; leftover load/surplus is unserved / curtailed, not priced.
          unserved = Math.abs(grid);
          grid = 0;
        } else if (!allowExport && grid < 0) {
          // Curtail export: no export revenue on this hour.
          grid = 0;
        }

        // LCOE is once per stored kWh delivered, not on the charge leg.
        const wear = batteryLcoePerKwh * (dischargeKwh / IDEAL_ETA);
        const cost =
          hourCost(price, grid) +
          wear +
          unserved * UNSERVED_PENALTY +
          dp[h + 1][t];
        const movedKwh = chargeKwh + dischargeKwh;
        // Flat-price tie-break: do not cycle the battery when cost is the same.
        const better =
          cost < best - 1e-9 ||
          (Math.abs(cost - best) <= 1e-9 &&
            (movedKwh < bestMoved - 1e-9 ||
              (Math.abs(movedKwh - bestMoved) <= 1e-9 && t === s)));
        if (better) {
          best = cost;
          bestTo = t;
          bestMoved = movedKwh;
        }
      }
      dp[h][s] = best;
      nextIdx[h][s] = bestTo;
    }
  }

  if (!Number.isFinite(dp[0][startIdx]) || dp[0][startIdx] >= INF / 2)
    return null;

  const hours = [];
  let s = startIdx;
  let costIdeal = 0;
  let costNoBess = 0;

  for (let h = 0; h < HOURS; h++) {
    const t = nextIdx[h][s];
    if (t < 0) return null;
    const fromSoc = indexToSoc(s);
    const toSoc = indexToSoc(t);
    const moved = transitionEnergy(fromSoc, toSoc, capacityKwh);
    const chargeKwh = moved.chargeKwh;
    const dischargeKwh = moved.dischargeKwh;
    let grid = load[h] - pv[h] + chargeKwh - dischargeKwh;
    let unservedKwh = 0;
    if (off[h]) {
      unservedKwh = Math.abs(grid);
      grid = 0;
    } else if (!allowExport && grid < 0) {
      grid = 0;
    }

    let gridNoBess = load[h] - pv[h];
    if (off[h]) gridNoBess = 0;
    else if (!allowExport && gridNoBess < 0) gridNoBess = 0;

    const wear = batteryLcoePerKwh * (dischargeKwh / IDEAL_ETA);
    costIdeal += hourCost(prices[h], grid) + wear;
    costNoBess += hourCost(prices[h], gridNoBess);

    hours.push({
      socPercent: toSoc,
      gridKwh: grid,
      chargeKwh,
      dischargeKwh,
      unservedKwh,
    });
    s = t;
  }

  let costActual = null;
  if (
    Array.isArray(input.actualGridKwh) &&
    input.actualGridKwh.length === HOURS
  ) {
    let sum = 0;
    let any = false;
    for (let h = 0; h < HOURS; h++) {
      const g = input.actualGridKwh[h];
      if (g == null || !Number.isFinite(Number(g))) continue;
      any = true;
      sum += hourCost(prices[h], Number(g));
    }
    if (any) costActual = sum;
  }

  return {
    hours,
    costNoBess,
    costIdeal,
    costActual,
    savingVsNoBess: costNoBess - costIdeal,
    savingVsActual: costActual != null ? costActual - costIdeal : null,
  };
}
