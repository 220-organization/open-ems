import fs from 'fs';
import path from 'path';
import bg from './locales/bg.json';
import cs from './locales/cs.json';
import de from './locales/de.json';
import en from './locales/en.json';
import es from './locales/es.json';
import fr from './locales/fr.json';
import nl from './locales/nl.json';
import pl from './locales/pl.json';
import uk from './locales/uk.json';
import {
  SLOW_DOWNLINK_MBPS,
  SLOW_NOTICE_DELAY_MS,
  SLOW_RTT_MS,
  isSlowConnection,
  shouldArmSlowNoticeTimer,
} from './slowNetNotice';

const indexHtml = fs.readFileSync(path.join(__dirname, '../public/index.html'), 'utf8');

describe('isSlowConnection', () => {
  it('treats offline, 2g, save-data, high rtt, and very low downlink as slow', () => {
    expect(isSlowConnection(null, false)).toBe(true);
    expect(isSlowConnection({ effectiveType: 'slow-2g' }, true)).toBe(true);
    expect(isSlowConnection({ effectiveType: '2g' }, true)).toBe(true);
    expect(isSlowConnection({ saveData: true, effectiveType: '4g' }, true)).toBe(true);
    expect(isSlowConnection({ effectiveType: '4g', rtt: SLOW_RTT_MS }, true)).toBe(true);
    expect(isSlowConnection({ effectiveType: '3g', downlink: SLOW_DOWNLINK_MBPS - 0.05 }, true)).toBe(true);
  });

  it('leaves a normal link alone, including an unknown downlink of 0', () => {
    expect(isSlowConnection(null, true)).toBe(false);
    expect(isSlowConnection({ effectiveType: '4g', rtt: 80, downlink: 10 }, true)).toBe(false);
    expect(isSlowConnection({ effectiveType: '4g', downlink: 0 }, true)).toBe(false);
    expect(isSlowConnection({ effectiveType: '3g', rtt: 400, downlink: 1.5 }, true)).toBe(false);
  });
});

describe('shouldArmSlowNoticeTimer', () => {
  it('skips loopback so a local compile is not reported as a slow link', () => {
    expect(shouldArmSlowNoticeTimer('localhost')).toBe(false);
    expect(shouldArmSlowNoticeTimer('127.0.0.1')).toBe(false);
    expect(shouldArmSlowNoticeTimer('::1')).toBe(false);
    expect(shouldArmSlowNoticeTimer('220-km.com')).toBe(true);
  });
});

describe('boot splash copy', () => {
  const bundles = [en, uk, es, pl, cs, nl, bg, fr, de];

  it('inlines every locale message so the notice can render before the bundle', () => {
    for (const bundle of bundles) {
      expect(indexHtml).toContain(bundle.slowInternetMessage);
      expect(indexHtml).toContain(bundle.slowInternetReconnect);
      expect(indexHtml).toContain(bundle.slowInternetLoading);
    }
    expect(indexHtml).toContain(`SLOW_NOTICE_DELAY_MS = ${SLOW_NOTICE_DELAY_MS}`);
    expect(indexHtml).toContain(`SLOW_RTT_MS = ${SLOW_RTT_MS}`);
    expect(indexHtml).toContain(`SLOW_DOWNLINK_MBPS = ${SLOW_DOWNLINK_MBPS}`);
  });
});
