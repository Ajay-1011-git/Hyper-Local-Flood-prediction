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
 * SELECTION HIGHLIGHT (T4C.1)
 * ---------------------------------------------------------------
 * `sceneStore.highlightedStructureId` (set by the risk-ranking list's own
 * row click) gets a real emissive glow layered on top of its real
 * severity color — the User Flow doc's own cross-linking requirement
 * ("clicking a row ... highlights that structure in the 3D scene").
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
import * as THREE from 'three'

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
  const highlightedStructureId = useSceneStore((s) => s.highlightedStructureId)

  useEffect(() => {
    if (!data) return

    // Remember each material's REAL base colour once, so severity can be
    // applied as a reversible tint. Without this, the first repaint would
    // become the new "base" and the building could never return to
    // looking like a building.
    for (const material of data.materialsByName.values()) {
      if (!material.userData.baseColor) {
        material.userData.baseColor = material.color.clone()
      }
      material.color.copy(material.userData.baseColor as THREE.Color)
      material.emissive.set('#000000')
      material.emissiveIntensity = 0
    }

    const maxRiskScore = damageRanking.reduce(
      (max, entry) => Math.max(max, entry.risk_score),
      0,
    )

    /**
     * Applies one structure's real severity WITHOUT replacing its base
     * colour.
     *
     * An earlier version did `material.color.set(SEVERITY_COLORS[...])`,
     * which repainted the whole structure. Because `Monitoring` (the
     * correct, honest state when there is no elevated risk) is blue, a
     * site with no flooding rendered every building and road solid blue —
     * reading as a rendering fault rather than as "no elevated risk", and
     * burying the real material under a flat colour.
     *
     * Severity is now a BLEND toward the severity colour, scaled by how
     * severe it actually is: `Monitoring` leaves the real material
     * completely untouched (nothing to show), and the higher states tint
     * progressively harder and add emissive so they read at a glance.
     * The palette is unchanged, so this still agrees with the ranking
     * list and the citizen view — and, per the User Flow's §7
     * accessibility rule, severity is never communicated by colour alone:
     * `RiskRankingList` carries the real text label.
     */
    const applySeverity = (
      material: THREE.MeshStandardMaterial,
      severity: (typeof SEVERITY_ORDER)[number],
      highlighted: boolean,
    ) => {
      const step = SEVERITY_ORDER.indexOf(severity)
      const base = material.userData.baseColor as THREE.Color
      if (step > 0) {
        // 0.30 / 0.55 / 0.80 for Watch / Warning / Critical.
        const blend = 0.05 + step * 0.25
        material.color.copy(base).lerp(new THREE.Color(SEVERITY_COLORS[severity]), blend)
        material.emissive.set(SEVERITY_COLORS[severity])
        material.emissiveIntensity = 0.12 * step
      }
      if (highlighted) {
        material.emissive.set('#eae2ef')
        material.emissiveIntensity = 0.55
      }
    }

    const buildingEntries = damageRanking.filter(
      (entry): entry is DamageRankEntry => entry.structure_type === 'building',
    )
    for (const entry of buildingEntries) {
      const material = data.materialsByName.get(entry.structure_id)
      if (!material) continue // real entry for a structure this GLB doesn't have — skip, don't guess
      applySeverity(
        material,
        severityForEntry(entry, currentHour, maxRiskScore),
        entry.structure_id === highlightedStructureId,
      )
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
        applySeverity(
          roadMaterial,
          SEVERITY_ORDER[worstSeverityIndex],
          roadEntries.some((entry) => entry.structure_id === highlightedStructureId),
        )
      }
    }
  }, [data, damageRanking, currentHour, highlightedStructureId])

  return null
}

export default DamageOverlay
