import {
  evStationPowerPortsToPoll,
  pickClusterSocPercent,
  sumBoundEvPortsPowerW,
} from './powerFlowEngine';

describe('pickClusterSocPercent', () => {
  it('returns station SoC once when every cluster row has the same plant value', () => {
    expect(
      pickClusterSocPercent([
        { socPercent: 38.666667, batteryPowerW: 1450 },
        { socPercent: 38.666667, batteryPowerW: 3250 },
        { socPercent: 38.666667, batteryPowerW: 2750 },
      ])
    ).toBeCloseTo(38.666667, 5);
  });

  it('does not sum SoC across cluster serials', () => {
    const v = pickClusterSocPercent([
      { socPercent: 39 },
      { socPercent: 39 },
      { socPercent: 39 },
    ]);
    expect(v).toBe(39);
    expect(v).not.toBe(117);
  });

  it('averages when plant values differ', () => {
    expect(pickClusterSocPercent([{ socPercent: 47 }, { socPercent: 24 }, { socPercent: 45 }])).toBeCloseTo(
      (47 + 24 + 45) / 3,
      5
    );
  });

  it('returns null when no SoC is present', () => {
    expect(pickClusterSocPercent([{ batteryPowerW: 1000 }])).toBeNull();
    expect(pickClusterSocPercent([])).toBeNull();
  });
});

describe('evStationPowerPortsToPoll', () => {
  it('returns all bound ports when inverter has multiple EV ports', () => {
    expect(
      evStationPowerPortsToPoll({ stationFilter: '634', boundPortNumbers: ['634', '635'] })
    ).toEqual(['634', '635']);
  });

  it('falls back to selected station when no binding', () => {
    expect(evStationPowerPortsToPoll({ stationFilter: '634', boundPortNumbers: [] })).toEqual(['634']);
  });
});

describe('sumBoundEvPortsPowerW', () => {
  it('sums live power from charging-ports rows', () => {
    expect(
      sumBoundEvPortsPowerW(['634', '635'], [
        { number: '634', powerWt: 35160 },
        { number: '635', powerWt: 39000 },
      ])
    ).toBe(74160);
  });

  it('returns 0 when bound ports have no active power', () => {
    expect(
      sumBoundEvPortsPowerW(['634', '635'], [
        { number: '634', powerWt: null },
        { number: '635', powerWt: 0 },
      ])
    ).toBe(0);
  });
});
