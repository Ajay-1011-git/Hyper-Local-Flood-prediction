/**
 * TypeScript mirrors of this project's real Pydantic contracts.
 *
 * Field names are IDENTICAL to `backend/shared/contracts.py` and
 * `backend/stage4/shared/contracts.py` — per T4B.0's own requirement
 * ("typed against the real contracts... keep field names identical").
 * Transcribed directly from those files, not paraphrased: a renamed
 * field here would silently break deserialization at runtime, since
 * nothing validates these against the Python side automatically.
 *
 * Optional fields use `| null` (not `?`) where the Python side is
 * `Optional[...] = None` and really does serialize as JSON `null`,
 * rather than being omitted.
 */

/** Stage 2 — `backend/shared/contracts.py::NodeState` */
export interface NodeState {
  node_id: string
  hour: number
  depth_mean_m: number
  depth_min_m: number
  depth_max_m: number
  velocity_mean_mps: number
  velocity_min_mps: number
  velocity_max_mps: number
  rate_of_rise: number
  ensemble_agreement_fraction: number
  building_id: string | null
  road_segment_id: string | null
}

/** Stage 2 — `backend/shared/contracts.py::SimulationResult` */
export interface SimulationResult {
  simulation_id: string
  site_id: string
  source_forecast_id: string
  generated_at: string
  hazard_threshold_m: number
  validation_error_m: number
  node_states: NodeState[]
  envelope: Record<string, unknown>
}

/** Stage 2 — `backend/shared/contracts.py::TerrainGrid` */
export interface TerrainGrid {
  site_id: string
  resolution_m: number
  origin_lat: number
  origin_lon: number
  elevation_grid: number[][]
  /** Honesty flag: DEM-derived, not surveyed. Surfaced on /about (T4C.6). */
  interpolated_from_regional_dem: boolean
}

/**
 * Stage 4 — `backend/stage4/shared/contracts.py::TerrainHeightmap` (T4B.3).
 *
 * A RENDERING view of terrain, distinct from Stage 2's `TerrainGrid`
 * simulation contract above. `elevation_grid` cells are `null` where the
 * real DEM has nodata (CartoDEM voids / values Stage 1B masked as
 * implausible) — the backend refuses to fill them with a number, so the
 * renderer must decide and disclose how it handles them.
 */
export interface TerrainHeightmap {
  min_lat: number
  max_lat: number
  min_lon: number
  max_lon: number
  rows: number
  cols: number
  /** Real ground spacing of THIS grid, after decimation. */
  resolution_m: number
  elevation_grid: (number | null)[][]
  /** Over finite cells only. */
  min_elevation_m: number
  max_elevation_m: number
  nodata_cell_count: number
}

/**
 * Stage 4 — `backend/stage4/scene/mesh_nodes.py::MeshNodePosition` (T4B.5).
 *
 * One real Stage 2 `ComputationalMeshNode`'s position, reconstructed by
 * Stage 4 (see that module's docstring for why/how) in the EXACT scene
 * frame `Terrain.tsx`/`SiteMesh.tsx` already use: `x_m`=east, `z_m`=-north,
 * `elevation_m`=real absolute elevation (world Y). `node_id` matches the
 * real `NodeState.node_id` the live simulation emits (`"n_{row}_{col}"`),
 * so `WaterSurface.tsx` can look up each vertex's live depth by this id.
 */
export interface MeshNodePosition {
  node_id: string
  x_m: number
  z_m: number
  elevation_m: number
}

/** Stage 4 — `GET /api/mesh-nodes/{site_id}` (T4B.5). */
export interface SiteMeshNodesResponse {
  site_id: string
  rows: number
  cols: number
  resolution_m: number
  nodes: MeshNodePosition[]
}

/** Stage 4 — `GET /api/terrain/{site_id}` (T4B.3). */
export interface SiteTerrainResponse {
  site_id: string
  site_lat: number
  site_lon: number
  /** Always true: DEM-derived, never a survey. Must be stated on /about. */
  interpolated_from_regional_dem: boolean
  source_raster: string
  /** Decimated wide surround (TRD §6 point 3). */
  regional: TerrainHeightmap
  /** Finer patch from the SAME raster — seamless with `regional` by construction. */
  site: TerrainHeightmap
}

/** Stage 2 — `backend/shared/contracts.py::BuildingFootprint` */
export interface BuildingFootprint {
  building_id: string
  /** `[[x, y], ...]` real-world meters, site-local frame */
  footprint_polygon: number[][]
  height_m: number | null
}

/** Stage 3 — `backend/shared/contracts.py::RoadSegment` */
export interface RoadSegment {
  segment_id: string
  /** `[[x, y], ...]` real-world meters, site-local frame */
  polyline: number[][]
  width_m: number | null
}

/** Stage 3 — `backend/shared/contracts.py::DamageRankEntry` */
export interface DamageRankEntry {
  structure_id: string
  /** "building" | "road_segment" */
  structure_type: string
  site_id: string
  hazard_score: number
  exposure_score: number
  vulnerability_score: number
  /** Real citation, never blank. */
  vulnerability_source: string
  /** Always false unless real local calibration data exists. */
  vulnerability_is_local_calibration: boolean
  risk_score: number
  /** From `ensemble_agreement_fraction`. */
  confidence: number
  rank: number
  peak_hour: number
  peak_depth_m: number
  peak_velocity_mps: number
  peak_rate_of_rise: number
}

/** Stage 1B — `backend/shared/contracts.py::SensorReading` */
export interface SensorReading {
  sensor_id: string
  site_id: string
  distance_cm: number
  timestamp: string
  assimilated: boolean
}

/** Stage 1B — `backend/shared/contracts.py::DownscaledForecastField` */
export interface DownscaledTimestepValue {
  hour: number
  inflow_mm: number
}

export interface DownscaledEnsembleMember {
  member_id: number
  trajectory: DownscaledTimestepValue[]
}

export interface DownscaledForecastField {
  site_id: string
  site_lat: number
  site_lon: number
  resolution_km: number
  calibration_source: string
  /** "calibrated_nearby_station" | "computed_only_no_nearby_station" */
  calibration_confidence: string
  source_forecast_id: string
  generated_at: string
  members: DownscaledEnsembleMember[]
}

/** Stage 1A — `backend/shared/contracts.py::RegionalEnsembleForecast` */
export interface TimestepValue {
  hour: number
  rainfall_mm: number
}

export interface EnsembleMember {
  member_id: number
  trajectory: TimestepValue[]
}

export interface BoundingBox {
  min_lat: number
  max_lat: number
  min_lon: number
  max_lon: number
}

export interface RegionalEnsembleForecast {
  forecast_id: string
  /** "GEFS" | "WeatherNext2_Cyclones_Mini" — which real source produced this. */
  source: string
  region_bbox: BoundingBox
  generated_at: string
  resolution_km: number
  members: EnsembleMember[]
}

/** Stage 4 — `backend/stage4/shared/contracts.py::Alert` */
export interface Alert {
  id: string
  site_id: string
  generated_at: string
  /** Real CAP severity enum value. */
  severity: string
  /** From real ensemble agreement — never a placeholder. */
  certainty: number
  /** Real CAP urgency enum value. */
  urgency: string
  /** `[[lat, lon], ...]` */
  area_polygon: number[][]
  effective_time: string
  expiry_time: string
  cap_xml: string
  /** e.g. `{ en: "...", ta: "...", hi: "..." }` */
  text_by_language: Record<string, string>
}

/**
 * WebSocket event contract (§B.2 of the Stage 4 build document).
 * See `api/websocket.ts` for the real, documented caveat about WHICH
 * endpoint actually emits which of these today.
 *
 * `sensor_assimilated`'s `updated_region` shape is transcribed from the
 * two REAL broadcast call sites, not the contract's own loose prose:
 *   - Stage 2 (stage2/routes.py, T2.8): `{ node_states: NodeState[] }`,
 *     the real nodes T2.8's local ghost-cell nudge actually changed.
 *   - Stage 1B (stage1b/sensor/ingest.py): always `null` — "no Stage 2
 *     simulation exists yet" from that module's own comment. Real and
 *     honest, not a bug: Stage 1B has no simulation to update.
 */
export type SiteSocketEvent =
  | { type: 'simulation_update'; payload: { node_states: NodeState[]; envelope: Record<string, unknown> } }
  | {
      type: 'sensor_assimilated'
      payload: {
        sensor_id: string
        new_reading: SensorReading
        updated_region: { node_states: NodeState[] } | null
      }
    }
  | { type: 'ranking_update'; payload: DamageRankEntry[] }
