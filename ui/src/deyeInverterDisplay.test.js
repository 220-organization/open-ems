import {
  compareInvertersByAddedAtDesc,
  evPortStationNumbersForInverter,
  sourceMenuTextMatches,
} from "./deyeInverterDisplay";

describe("compareInvertersByAddedAtDesc", () => {
  it("puts the newest plant first", () => {
    const rows = [
      { shortLabel: "Old", createdAt: 100 },
      { shortLabel: "New", createdAt: 300 },
      { shortLabel: "Mid", createdAt: 200 },
    ];
    expect(
      rows.sort(compareInvertersByAddedAtDesc).map((r) => r.shortLabel),
    ).toEqual(["New", "Mid", "Old"]);
  });

  it("keeps undated plants after dated ones", () => {
    const rows = [
      { shortLabel: "Zebra", createdAt: null },
      { shortLabel: "Alpha", createdAt: 10 },
    ];
    expect(
      rows.sort(compareInvertersByAddedAtDesc).map((r) => r.shortLabel),
    ).toEqual(["Alpha", "Zebra"]);
  });
});

describe("evPortStationNumbersForInverter", () => {
  it("binds BESS 500 Solar City to startMany ports 683 and 684", () => {
    expect(
      evPortStationNumbersForInverter(
        "2509280309",
        "BESS 500 Solar City — 2509280309",
      ),
    ).toEqual(["683", "684"]);
    expect(
      evPortStationNumbersForInverter(
        "2512011265",
        "BESS 500 Solar City — 2512011265",
        ["2509280309", "2512011265"],
      ),
    ).toEqual(["683", "684"]);
  });
});

describe("sourceMenuTextMatches", () => {
  it("matches a case-insensitive substring", () => {
    expect(sourceMenuTextMatches("BESS 500 Solar City · 37%", "bess")).toBe(
      true,
    );
    expect(sourceMenuTextMatches("BESS 500 Solar City", "odesa")).toBe(false);
    expect(sourceMenuTextMatches("anything", "  ")).toBe(true);
  });
});
