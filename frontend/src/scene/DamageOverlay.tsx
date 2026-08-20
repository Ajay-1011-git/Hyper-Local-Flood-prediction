/**
 * Damage overlay (T4B.7).
 *
 * Recolors the real `Building_01`/`Building_02` (and, with a disclosed
 * limitation below, `Road_Network`) materials per Stage 3's real
 * `DamageRankEntry.risk_score`, using the four-state severity palette
 * (`../severity.ts`, transcribed from the User Flow doc's own §1 table),
 * as the timeline advances past each structure's real `peak_hour`.
 *
 * MUTATES SiteMesh's OWN MATERIALS — RENDERS NOTHING ITSELF
 * ---------------------------------------------------------------
 * This component fetches the SAME `queryKeys.siteMesh(siteId)` cache
 * entry `SiteMesh.tsx` populates (TanStack Query dedupes identical
 * key+queryFn calls to one shared cache entry/one real fetch — confirmed
 * current behavior in this session) and reaches into
 * `SiteMeshFetchResult.materialsByName` to set `.color` directly on the
 * REAL, already-mounted materials. It does not mount a `<primitive>` of
 * its own: two components rendering the SAME `THREE.Object3D` would
 * fight over its single parent slot in the scene graph. `SiteMesh.tsx`
 * was changed (this task) to give each real named object its own cloned
 * material specifically so this mutation is safe and independent per
 * structure.
 *
 * A REAL GEOMETRY LIMITATION, DISCLOSED RATHER THAN FAKED
 * ---------------------------------------------------------------
 * The real GLB has exactly ONE merged `Road_Network` mesh (confirmed:
 * `stage2/ingestion/glb_loader.py`'s `REQUIRED_OBJECT_NAMES` has no
 * per-segment nodes) — Stage 3's 41 real `RoadSegment`s exist only as
 * hazard-analysis geometry (`road_segmentation.py`), never as separate
 * visual meshes. Individual road segments therefore cannot be recolored
 * independently in the 3D scene. This component tints the WHOLE
 * `Road_Network` by whichever real road segment is currently at the
 * worst (highest) severity — a real, disclosed aggregation, not
 * fabricated per-segment geometry that doesn't exist.
 */

import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'

import type { DamageRankEntry } from '../api/types'
import { queryKeys } from '../api/client'
import { SEVERITY_COLORS, SEVERITY_ORDER, severityForEntry } from '../severity'
import { useSceneStore } from '../store/sceneStore'
import { fetchSiteMeshScene } from './SiteMesh'

export interface DamageOverlayProps {
  siteId: string
}

export function DamageOverlay({ siteId }: DamageOverlayProps) {
  const { data } = useQuery({
    queryKey: queryKeys.siteMesh(siteId),
    queryFn: () => fetchSiteMeshScene(siteId),
    staleTime: Infinity,
    retry: false,
  })

  const damageRanking = useSceneStore((s) => s.damageRanking)
  const currentHour = useSceneStore((s) => s.currentHour)

  useEffect(() => {
    if (!data) return

    const maxRiskScore = damageRanking.reduce(
      (max, entry) => Math.max(max, entry.risk_score),
      0,
    )

    const buildingEntries = damageRanking.filter(
      (entry): entry is DamageRankEntry => entry.structure_type === 'building',
    )
    for (const entry of buildingEntries) {
      const material = data.materialsByName.get(entry.structure_id)
      if (!material) continue // real entry for a structure this GLB doesn't have — skip, don't guess
      const severity = severityForEntry(entry, currentHour, maxRiskScore)
      material.color.set(SEVERITY_COLORS[severity])
    }

    const roadEntries = damageRanking.filter(
      (entry): entry is DamageRankEntry => entry.structure_type === 'road_segment',
    )
    if (roadEntries.length > 0) {
      const roadMaterial = data.materialsByName.get('Road_Network')
      if (roadMaterial) {
        let worstSeverityIndex = 0
        for (const entry of roadEntries) {
          const severity = severityForEntry(entry, currentHour, maxRiskScore)
          worstSeverityIndex = Math.max(worstSeverityIndex, SEVERITY_ORDER.indexOf(severity))
        }
        roadMaterial.color.set(SEVERITY_COLORS[SEVERITY_ORDER[worstSeverityIndex]])
      }
    }
  }, [data, damageRanking, currentHour])

  return null
}

export default DamageOverlay
