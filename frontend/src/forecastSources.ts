/**
 * The app's one real regional-forecast-source label map — shared by
 * `EnsembleFanChart.tsx` (the dashboard's fan chart) and `About.tsx`
 * (the "which source is powering the current display" honesty
 * disclosure, T4C.6) so the two can never label the same real
 * `RegionalEnsembleForecast.source` value differently.
 *
 * Real values, per Stage 1A's own CLAUDE.md ("GEFS -> WeatherNext 2
 * Cyclones Mini... GenCast has been removed entirely"): `"GEFS"` (0.25°,
 * primary) and `"WeatherNext2_Cyclones_Mini"` (1.0°, fallback). No third
 * value/GenCast entry — resurrecting one without the source itself
 * changing would silently mislabel real data.
 */
export const FORECAST_SOURCE_LABELS: Record<string, string> = {
  GEFS: 'GEFS (0.25°)',
  WeatherNext2_Cyclones_Mini: 'WeatherNext 2 Mini (1.0°)',
}

export function forecastSourceLabel(source: string): string {
  return FORECAST_SOURCE_LABELS[source] ?? source
}
