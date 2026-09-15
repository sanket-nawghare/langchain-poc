import { describe, expect, it } from "vitest";

import { createFrontendConfig } from "./config";

describe("createFrontendConfig", () => {
  it("uses the documented local default", () => {
    expect(createFrontendConfig({}).apiBaseUrl).toBe("http://localhost:8000");
  });

  it("normalizes a trailing slash", () => {
    expect(
      createFrontendConfig({
        VITE_API_BASE_URL: "https://api.example.test/",
      }).apiBaseUrl,
    ).toBe("https://api.example.test");
  });

  it.each(["relative/path", "ftp://api.example.test"])(
    "rejects invalid API URL %s",
    (apiBaseUrl) => {
      expect(() =>
        createFrontendConfig({ VITE_API_BASE_URL: apiBaseUrl }),
      ).toThrow(/VITE_API_BASE_URL/);
    },
  );
});
