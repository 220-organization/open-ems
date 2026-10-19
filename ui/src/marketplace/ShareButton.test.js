import { buildMarketplaceLocationShareUrl } from './ShareButton';

describe('marketplace location share url', () => {
  it('includes the location id and language', () => {
    const url = buildMarketplaceLocationShareUrl('abc-123', {
      origin: 'http://localhost:9220',
      lang: 'uk',
    });
    const parsed = new URL(url);
    expect(parsed.origin).toBe('http://localhost:9220');
    expect(parsed.pathname).toBe('/marketplace');
    expect(parsed.searchParams.get('location')).toBe('abc-123');
    expect(parsed.searchParams.get('lang')).toBe('uk');
  });

  it('omits language when it is empty', () => {
    const url = buildMarketplaceLocationShareUrl('loc-1', {
      origin: 'https://220-km.com:9220',
      lang: '',
    });
    const parsed = new URL(url);
    expect(parsed.searchParams.get('location')).toBe('loc-1');
    expect(parsed.searchParams.has('lang')).toBe(false);
  });
});
