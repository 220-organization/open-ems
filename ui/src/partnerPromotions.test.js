import { hubPartnerIndexById, readPinnedHubLogoIndexFromUrl } from './partnerPromotions';

describe('hub logo URL pin', () => {
  it('resolves known partner ids', () => {
    expect(hubPartnerIndexById('dtek-kem')).toBeGreaterThan(0);
    expect(hubPartnerIndexById('ecu')).toBeGreaterThan(0);
    expect(hubPartnerIndexById('vyriy')).toBe(0);
  });

  it('rejects unknown ids', () => {
    expect(hubPartnerIndexById('')).toBe(-1);
    expect(hubPartnerIndexById('not-a-partner')).toBe(-1);
  });

  it('reads logo query from search string', () => {
    expect(readPinnedHubLogoIndexFromUrl('?market=oree&zone=ES&logo=dtek-kem')).toBe(
      hubPartnerIndexById('dtek-kem'),
    );
    expect(readPinnedHubLogoIndexFromUrl('market=oree&logo=ecu')).toBe(hubPartnerIndexById('ecu'));
    expect(readPinnedHubLogoIndexFromUrl('?market=oree&zone=ES')).toBe(-1);
  });
});
