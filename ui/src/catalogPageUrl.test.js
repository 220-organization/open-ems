import { catalogPageUrlFromLocation } from "./catalogPageUrl";

describe("catalogPageUrlFromLocation", () => {
  beforeEach(() => {
    window.history.replaceState(
      {},
      "",
      "/buy-commercial-charger?brand=infi&power=160plus#catalog",
    );
  });

  it("keeps the filter query the user has in the address bar", () => {
    const url = new URL(catalogPageUrlFromLocation());
    expect(url.origin).toBe(window.location.origin);
    expect(url.pathname).toBe("/buy-commercial-charger");
    expect(url.searchParams.get("brand")).toBe("infi");
    expect(url.searchParams.get("power")).toBe("160plus");
    expect(url.hash).toBe("");
  });

  it("adds the chosen sku without dropping filters", () => {
    const url = new URL(catalogPageUrlFromLocation({ sku: "INF-160" }));
    expect(url.searchParams.get("brand")).toBe("infi");
    expect(url.searchParams.get("power")).toBe("160plus");
    expect(url.searchParams.get("sku")).toBe("INF-160");
  });
});
