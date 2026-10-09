import {
  evStationPowerPortsToPoll,
  formatInverterOfflineAge,
  formatInverterOfflineLabel,
  formatInverterUpdatedAgo,
  pickClusterLiveStatus,
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

describe('formatInverterUpdatedAgo', () => {
  const t = (key, vars) => `${key}:${vars.n}`;
  const now = 1_700_000_000_000;

  it('picks secs, mins, hours, and days', () => {
    expect(formatInverterUpdatedAgo(1_700_000_000 - 12, now, t)).toBe('inverterUpdatedSecs:12');
    expect(formatInverterUpdatedAgo(1_700_000_000 - 1, now, t)).toBe('inverterUpdatedSec:1');
    expect(formatInverterUpdatedAgo(1_700_000_000 - 3 * 60, now, t)).toBe('inverterUpdatedMins:3');
    expect(formatInverterUpdatedAgo(1_700_000_000 - 2 * 3600, now, t)).toBe('inverterUpdatedHours:2');
    expect(formatInverterUpdatedAgo(1_700_000_000 - 5 * 86400, now, t)).toBe('inverterUpdatedDays:5');
  });
});

describe('formatInverterOfflineAge', () => {
  const t = (key, vars) => `${key}:${vars.n}`;
  const now = 1_700_000_000_000;

  it('uses minutes, hours, and days', () => {
    expect(formatInverterOfflineAge(1_700_000_000 - 3 * 60, now, t)).toBe('inverterOfflineMins:3');
    expect(formatInverterOfflineAge(1_700_000_000 - 2 * 3600, now, t)).toBe('inverterOfflineHours:2');
    expect(formatInverterOfflineAge(1_700_000_000 - 5 * 86400, now, t)).toBe('inverterOfflineDays:5');
  });

  it('returns empty when the sample time is missing', () => {
    expect(formatInverterOfflineAge(null, now, t)).toBe('');
    expect(formatInverterOfflineLabel(null, now, key => (key === 'inverterOffline' ? 'не в мережі' : key))).toBe(
      'не в мережі'
    );
  });
});

describe('pickClusterLiveStatus', () => {
  it('uses the newest collection time and stays online if any member is online', () => {
    expect(
      pickClusterLiveStatus([
        { collectionTime: 100, online: false },
        { collectionTime: 250, online: true },
      ])
    ).toEqual({ collectionTime: 250, online: true });
  });

  it('is offline only when every member is offline', () => {
    expect(
      pickClusterLiveStatus([
        { collectionTime: 100, online: false },
        { collectionTime: 80, online: false },
      ])
    ).toEqual({ collectionTime: 100, online: false });
  });
});
