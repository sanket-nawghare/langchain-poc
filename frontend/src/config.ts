export interface FrontendEnvironment {
  readonly VITE_API_BASE_URL?: string;
}

export interface FrontendConfig {
  readonly apiBaseUrl: string;
}

const defaultApiBaseUrl = "http://localhost:8000";

export function createFrontendConfig(
  environment: FrontendEnvironment,
): FrontendConfig {
  const candidate = environment.VITE_API_BASE_URL?.trim() || defaultApiBaseUrl;
  let url: URL;

  try {
    url = new URL(candidate);
  } catch {
    throw new Error("VITE_API_BASE_URL must be an absolute HTTP(S) URL");
  }

  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error("VITE_API_BASE_URL must use HTTP or HTTPS");
  }

  return Object.freeze({
    apiBaseUrl: url.toString().replace(/\/$/, ""),
  });
}

export const config = createFrontendConfig(import.meta.env);
