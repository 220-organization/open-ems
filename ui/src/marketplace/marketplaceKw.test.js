import {
  KW_MAX,
  KW_MIN,
  KW_SLIDER_MAX_INDEX,
  MARKER_SIZE_MAX_PX,
  MARKER_SIZE_MIN_PX,
  kwFromSliderIndex,
  markerSizePxForKw,
  sliderIndexFromKw,
  snapKwValue,
} from './marketplaceKw';

describe('marketplace kW slider', () => {
  it('starts at 7 kW then steps by 10 kW to 5000', () => {
    expect(kwFromSliderIndex(0)).toBe(KW_MIN);
    expect(kwFromSliderIndex(1)).toBe(10);
    expect(kwFromSliderIndex(2)).toBe(20);
    expect(kwFromSliderIndex(KW_SLIDER_MAX_INDEX)).toBe(KW_MAX);
  });

  it('maps kW back to slider index', () => {
    expect(sliderIndexFromKw(7)).toBe(0);
    expect(sliderIndexFromKw(10)).toBe(1);
    expect(sliderIndexFromKw(240)).toBe(24);
    expect(sliderIndexFromKw(5000)).toBe(KW_SLIDER_MAX_INDEX);
  });

  it('snaps in-between values onto 7 or 10 kW ticks', () => {
    expect(snapKwValue(8)).toBe(7);
    expect(snapKwValue(12)).toBe(10);
    expect(snapKwValue(16)).toBe(20);
    expect(snapKwValue(4999)).toBe(5000);
  });
});

describe('marketplace map marker size', () => {
  it('grows as kW grows', () => {
    const seven = markerSizePxForKw(7);
    const forty = markerSizePxForKw(40);
    const twoForty = markerSizePxForKw(240);
    const max = markerSizePxForKw(5000);
    expect(seven).toBe(MARKER_SIZE_MIN_PX);
    expect(max).toBe(MARKER_SIZE_MAX_PX);
    expect(forty).toBeGreaterThan(seven);
    expect(twoForty).toBeGreaterThan(forty);
    expect(max).toBeGreaterThan(twoForty);
  });
});
