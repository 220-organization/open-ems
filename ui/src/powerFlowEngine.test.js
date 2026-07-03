import {
  evStationPowerPortsToPoll,
  sumBoundEvPortsPowerW,
} from './powerFlowEngine';

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
