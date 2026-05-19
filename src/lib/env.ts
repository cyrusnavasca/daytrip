/**
 * Centralised env var access with fail-fast validation.
 * Import from here instead of process.env directly.
 */

function requireEnv(key: string): string {
  const val = process.env[key];
  if (!val) throw new Error(`Missing required env var: ${key}`);
  return val;
}

export const env = {
  // Database
  DATABASE_URL: () => requireEnv("DATABASE_URL"),

  // LLM
  OPENAI_API_KEY: () => requireEnv("OPENAI_API_KEY"),

  // Search — Tavily also handles Reddit via site:reddit.com queries
  TAVILY_API_KEY: () => requireEnv("TAVILY_API_KEY"),

  // Maps
  GOOGLE_MAPS_API_KEY: () => requireEnv("GOOGLE_MAPS_API_KEY"),
  NEXT_PUBLIC_MAPBOX_TOKEN: () => requireEnv("NEXT_PUBLIC_MAPBOX_TOKEN"),

  // Weather
  OPENWEATHER_API_KEY: () => requireEnv("OPENWEATHER_API_KEY"),
};
