import {
  HUB_PARTNER_PROMOTIONS,
  hubPartnerIndexById,
  readPinnedHubLogoIndexFromUrl,
} from './partnerPromotions';

describe('hub logo URL pin', () => {
  it('resolves known partner ids', () => {
    expect(hubPartnerIndexById('dtek-kem')).toBeGreaterThan(0);
    expect(hubPartnerIndexById('ecu')).toBeGreaterThan(0);
    expect(hubPartnerIndexById('atmosfera')).toBeGreaterThan(0);
    expect(hubPartnerIndexById('gridlab')).toBeGreaterThan(0);
    expect(hubPartnerIndexById('vyriy')).toBe(0);
    expect(HUB_PARTNER_PROMOTIONS.find(p => p.id === 'gridlab')?.logoDarkPad).toBe(true);
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

  it('defaults to 220-km when logo is absent', () => {
    expect(readPinnedHubLogoIndexFromUrl('?market=oree&zone=ES')).toBe(-1);
    expect(hubPartnerIndexById('vyriy')).toBe(0);
  });
});
