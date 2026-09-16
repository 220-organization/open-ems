import {
  HOME_CHARGER_DEFAULT_SORT,
  applyHomeChargerCatalogSearch,
  parseHomeChargerCatalogSearch,
} from "./buyHomeChargerUrl";

describe("buy-home-charger shareable query", () => {
  it("parses filters including spaced connector and brand", () => {
    const parsed = parseHomeChargerCatalogSearch(
      "?kind=accessory&power=7to8&connector=Type+2&phases=1&brand=SPARKS+CHARGERS&sort=power-desc&sku=2373289399",
    );
    expect(parsed).toEqual({
      kind: "accessory",
      power: "7to8",
      connector: "Type 2",
      phases: "1",
      brand: "SPARKS CHARGERS",
      sku: "2373289399",
      sort: "power-desc",
    });
  });

  it("ignores unknown filter values", () => {
    expect(
      parseHomeChargerCatalogSearch("?kind=bag&power=50&phases=2&sort=name"),
    ).toEqual({});
  });

  it("omits default sort from the query string and keeps lang", () => {
    const params = applyHomeChargerCatalogSearch(
      new URLSearchParams("lang=uk"),
      {
        kind: "charger",
        power: "22plus",
        connector: "Type 2",
        phases: "3",
        brand: "LADERGY",
        sku: "",
        sort: HOME_CHARGER_DEFAULT_SORT,
      },
    );
    expect(params.get("lang")).toBe("uk");
    expect(params.get("kind")).toBe("charger");
    expect(params.get("power")).toBe("22plus");
    expect(params.get("connector")).toBe("Type 2");
    expect(params.get("phases")).toBe("3");
    expect(params.get("brand")).toBe("LADERGY");
    expect(params.get("sort")).toBeNull();
    expect(params.get("sku")).toBeNull();
  });
});
