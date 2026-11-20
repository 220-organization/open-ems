import {
  computeIdealArbitrageDay,
  IDEAL_SOC_MIN,
  IDEAL_SOC_MAX,
} from "./idealArbitrage";

function hours(v) {
  return Array.from({ length: 24 }, () => v);
}

function baseInput(over = {}) {
  return {
    prices: hours(5),
    loadKwh: hours(2),
    pvKwh: hours(0),
    offGrid: hours(false),
    startSocPercent: 50,
    capacityKwh: 20,
    maxChargeKw: 5,
    maxDischargeKw: 5,
    allowExport: true,
    ...over,
  };
}

describe("computeIdealArbitrageDay", () => {
  test("returns null without capacity", () => {
    expect(computeIdealArbitrageDay(baseInput({ capacityKwh: 0 }))).toBeNull();
    expect(
      computeIdealArbitrageDay(baseInput({ capacityKwh: null })),
    ).toBeNull();
  });

  test("flat price leaves the battery idle", () => {
    const r = computeIdealArbitrageDay(baseInput());
    expect(r).not.toBeNull();
    expect(r.hours).toHaveLength(24);
    for (const h of r.hours) {
      expect(h.chargeKwh).toBeLessThan(1e-6);
      expect(h.dischargeKwh).toBeLessThan(1e-6);
      expect(h.socPercent).toBeCloseTo(50, 5);
    }
  });

  test("cheap night and expensive evening: charge then discharge within kW limits", () => {
    const prices = hours(5);
    for (let i = 0; i < 6; i++) prices[i] = 1;
    for (let i = 17; i < 21; i++) prices[i] = 20;
    const r = computeIdealArbitrageDay(
      baseInput({
        prices,
        loadKwh: hours(1),
        pvKwh: hours(0),
        startSocPercent: 20,
        capacityKwh: 40,
        maxChargeKw: 8,
        maxDischargeKw: 8,
        allowExport: true,
      }),
    );
    expect(r).not.toBeNull();
    const nightCharge = r.hours
      .slice(0, 6)
      .reduce((s, h) => s + h.chargeKwh, 0);
    const eveningDischarge = r.hours
      .slice(17, 21)
      .reduce((s, h) => s + h.dischargeKwh, 0);
    expect(nightCharge).toBeGreaterThan(1);
    expect(eveningDischarge).toBeGreaterThan(1);
    for (const h of r.hours) {
      expect(h.chargeKwh).toBeLessThanOrEqual(8 + 1e-6);
      expect(h.dischargeKwh).toBeLessThanOrEqual(8 + 1e-6);
    }
    expect(r.savingVsNoBess).toBeGreaterThan(0);
  });

  test("LCOE blocks a cycle that earns less than battery wear", () => {
    const prices = hours(0.02);
    for (let i = 12; i < 14; i++) prices[i] = 0.043;
    const r = computeIdealArbitrageDay(
      baseInput({
        prices,
        loadKwh: hours(0),
        startSocPercent: 10,
        capacityKwh: 10,
        maxChargeKw: 5.1,
        maxDischargeKw: 6.9,
        batteryLcoePerKwh: 1.61,
      }),
    );
    expect(r).not.toBeNull();
    for (const h of r.hours) {
      expect(h.chargeKwh).toBeLessThan(1e-6);
      expect(h.dischargeKwh).toBeLessThan(1e-6);
    }
  });

  test("wide spread still cycles after 10% RTE and LCOE", () => {
    const prices = hours(2);
    for (let i = 0; i < 4; i++) prices[i] = 0.01;
    for (let i = 18; i < 22; i++) prices[i] = 11;
    const r = computeIdealArbitrageDay(
      baseInput({
        prices,
        loadKwh: hours(0),
        startSocPercent: 10,
        capacityKwh: 10,
        maxChargeKw: 5,
        maxDischargeKw: 7,
        batteryLcoePerKwh: 1.61,
      }),
    );
    expect(r).not.toBeNull();
    const charged = r.hours.slice(0, 4).reduce((s, h) => s + h.chargeKwh, 0);
    const discharged = r.hours
      .slice(18, 22)
      .reduce((s, h) => s + h.dischargeKwh, 0);
    expect(charged).toBeGreaterThan(1);
    expect(discharged).toBeGreaterThan(1);
  });

  test("no export: grid stays at 0 or above; battery only covers load", () => {
    const prices = hours(5);
    for (let i = 0; i < 4; i++) prices[i] = 1;
    for (let i = 18; i < 22; i++) prices[i] = 15;
    const r = computeIdealArbitrageDay(
      baseInput({
        prices,
        loadKwh: hours(3),
        pvKwh: hours(0),
        startSocPercent: 40,
        capacityKwh: 30,
        maxChargeKw: 6,
        maxDischargeKw: 6,
        allowExport: false,
      }),
    );
    expect(r).not.toBeNull();
    for (const h of r.hours) {
      expect(h.gridKwh).toBeGreaterThanOrEqual(-1e-9);
    }
    expect(r.hours.some((h) => h.dischargeKwh > 0.1)).toBe(true);
  });

  test("off-grid hour: grid is 0 and SoC drops by the net load", () => {
    const offGrid = hours(false);
    offGrid[10] = true;
    const loadKwh = hours(0);
    loadKwh[10] = 4;
    const r = computeIdealArbitrageDay(
      baseInput({
        prices: hours(5),
        loadKwh,
        pvKwh: hours(0),
        offGrid,
        startSocPercent: 80,
        capacityKwh: 40,
        maxChargeKw: 10,
        maxDischargeKw: 10,
        allowExport: true,
      }),
    );
    expect(r).not.toBeNull();
    expect(r.hours[10].gridKwh).toBeCloseTo(0, 6);
    expect(r.hours[10].dischargeKwh).toBeGreaterThan(1);
    // End-of-hour SoC after covering ~4 kWh AC discharge from 80%.
    expect(r.hours[10].socPercent).toBeLessThan(80);
    expect(r.hours[10].socPercent).toBeGreaterThanOrEqual(IDEAL_SOC_MIN);
  });

  test("SoC stays between 10% and 100%", () => {
    const prices = hours(5);
    for (let i = 0; i < 8; i++) prices[i] = 0.5;
    for (let i = 12; i < 20; i++) prices[i] = 30;
    const r = computeIdealArbitrageDay(
      baseInput({
        prices,
        loadKwh: hours(0.5),
        pvKwh: hours(0),
        startSocPercent: 15,
        capacityKwh: 50,
        maxChargeKw: 20,
        maxDischargeKw: 20,
        allowExport: true,
      }),
    );
    expect(r).not.toBeNull();
    for (const h of r.hours) {
      expect(h.socPercent).toBeGreaterThanOrEqual(IDEAL_SOC_MIN - 1e-9);
      expect(h.socPercent).toBeLessThanOrEqual(IDEAL_SOC_MAX + 1e-9);
    }
  });
});
