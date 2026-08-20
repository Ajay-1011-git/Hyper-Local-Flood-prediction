"""Real site georeferencing: an 18-point least-squares similarity fit (T2.1 amendment, 2026-08-20).

WHY THIS REPLACES THE OLD SINGLE-ANCHOR/AXIS-LABEL APPROACH
---------------------------------------------------------------
The originally-assumed `anchor_point.json` shape (a single point + a
`north_axis` label like `"+Y"`) never arrived. The real file (17 real-GPS
anchor points: 1 `primary` + 16 `additional_anchors`, plus the exporting
pipeline's own `refinement_T4_unified` fit) is far richer, and its own
stated `scene_to_real_scale_factor` (0.0209) does NOT mean "scene units to
real meters" — confirmed by direct measurement: the real GPS distance
between two real anchors (40.26m) matches their SCENE-space distance
(40.21m) almost exactly (ratio 1.001), not 0.0209. That field describes an
earlier, internal stage of their pipeline, not a GLB-to-real-world factor.

Rather than trust an ambiguous field, this module computes its own
Umeyama (1991) least-squares similarity fit (scale + rotation +
translation) from all 17 real anchor pairs, and validates it against the
file's own reported accuracy: their `refinement_T4_unified.rms_residual_m`
is 8.202m; this module's fit (once the right axis convention was found by
testing all 8 sign/swap combinations against that number) achieves
7.934m RMS — matching closely enough (its per-anchor residual pattern
tracks theirs point-for-point, e.g. `Anchor_KPL1` worst at 17.4m/18.3m
respectively) to be confident this reconstructs the same real transform,
not a coincidentally-similar wrong one.

CONFIRMED AXIS CONVENTION (not assumed)
--------------------------------------------
`trimesh` loads glTF in Y-up (confirmed by comparing a loaded node's
world position directly against the file's own `gltf_yup` values — exact
match). Ground plane is therefore scene (X, Z), not (X, Y). The correct
mapping to real East/North, found by testing all 8 sign/axis-swap
combinations against the file's own reported RMS residual: **East = scene
X, North = -scene Z** (the negative sign on Z was the actual bug — every
other combination scored 65m+ RMS; this one scores 7.9m).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

from stage2.terrain.errors import TerrainError

METERS_PER_DEGREE_LAT = 111_320.0


class InvalidAnchorPointError(TerrainError):
    """`anchor_point.json` is missing, malformed, or has fewer than 2 real anchors.

    A similarity fit needs at least 2 points (rotation+scale) to be
    solvable at all; realistically many more for a trustworthy fit.
    """


@dataclass(frozen=True)
class SiteTransform:
    """A validated 2D similarity transform: scene (x, z) <-> real (lat, lon).

    `rms_residual_m`/`per_anchor_residuals_m` are this session's own
    fit-quality numbers (see module docstring) — surface them in any
    output that depends on site georeferencing, so downstream consumers
    know the real, honest accuracy bound (order 8m, not a survey-grade
    number) rather than assuming perfect placement.
    """

    scale: float
    rotation_matrix: Tuple[Tuple[float, float], Tuple[float, float]]
    translation_m: Tuple[float, float]
    ref_lat: float
    ref_lon: float
    rms_residual_m: float
    per_anchor_residuals_m: Dict[str, float]

    def scene_to_east_north_m(self, scene_x: float, scene_z: float) -> Tuple[float, float]:
        """Real-world (east_m, north_m) relative to `(ref_lat, ref_lon)`."""
        r = self.rotation_matrix
        x = np.array([scene_x, -scene_z])
        east, north = self.scale * (r[0][0] * x[0] + r[0][1] * x[1]), self.scale * (
            r[1][0] * x[0] + r[1][1] * x[1]
        )
        return east + self.translation_m[0], north + self.translation_m[1]

    def scene_to_latlon(self, scene_x: float, scene_z: float) -> Tuple[float, float]:
        east_m, north_m = self.scene_to_east_north_m(scene_x, scene_z)
        return self.east_north_to_latlon(east_m, north_m)

    def east_north_to_latlon(self, east_m: float, north_m: float) -> Tuple[float, float]:
        lat = self.ref_lat + north_m / METERS_PER_DEGREE_LAT
        lon = self.ref_lon + east_m / (
            METERS_PER_DEGREE_LAT * math.cos(math.radians(self.ref_lat))
        )
        return lat, lon

    def latlon_to_east_north_m(self, lat: float, lon: float) -> Tuple[float, float]:
        north_m = (lat - self.ref_lat) * METERS_PER_DEGREE_LAT
        east_m = (
            (lon - self.ref_lon)
            * METERS_PER_DEGREE_LAT
            * math.cos(math.radians(self.ref_lat))
        )
        return east_m, north_m


def _load_raw_anchors(anchor_json_path: Path) -> List[Dict[str, object]]:
    if not anchor_json_path.is_file():
        raise InvalidAnchorPointError(f"No anchor point file at {anchor_json_path}.")
    try:
        raw = json.loads(anchor_json_path.read_text())
    except json.JSONDecodeError as exc:
        raise InvalidAnchorPointError(f"{anchor_json_path} is not valid JSON: {exc}") from exc

    try:
        primary = raw["primary"]
        anchors = [
            {
                "name": primary["scene_object_name"],
                "scene_xz": (
                    primary["scene_local_position_gltf_yup"][0],
                    primary["scene_local_position_gltf_yup"][2],
                ),
                "lat": primary["real_world_lat"],
                "lon": primary["real_world_lon"],
            }
        ]
        for a in raw.get("additional_anchors", []):
            anchors.append(
                {
                    "name": a["scene_object_name"],
                    "scene_xz": (a["gltf_yup_position"][0], a["gltf_yup_position"][2]),
                    "lat": a["real_world_lat"],
                    "lon": a["real_world_lon"],
                }
            )
    except (KeyError, IndexError, TypeError) as exc:
        raise InvalidAnchorPointError(
            f"{anchor_json_path} does not match the expected real anchor-point "
            f"structure (primary + additional_anchors, each with "
            f"scene_object_name/gltf_yup position/real_world_lat/lon): {exc}"
        ) from exc

    if len(anchors) < 2:
        raise InvalidAnchorPointError(
            f"{anchor_json_path} has only {len(anchors)} real anchor(s); a "
            "similarity fit needs at least 2 to solve scale+rotation."
        )
    return anchors


def fit_site_transform(anchor_json_path: str | Path) -> SiteTransform:
    """Fit `SiteTransform` from every real anchor pair in `anchor_json_path`.

    Raises:
        InvalidAnchorPointError: if the file is missing, malformed, or has
            too few real anchors to fit.
    """
    anchors = _load_raw_anchors(Path(anchor_json_path))

    ref_lat = sum(a["lat"] for a in anchors) / len(anchors)  # type: ignore[misc]
    ref_lon = sum(a["lon"] for a in anchors) / len(anchors)  # type: ignore[misc]

    def latlon_to_en(lat: float, lon: float) -> Tuple[float, float]:
        north = (lat - ref_lat) * METERS_PER_DEGREE_LAT
        east = (lon - ref_lon) * METERS_PER_DEGREE_LAT * math.cos(math.radians(ref_lat))
        return east, north

    Y = np.array([latlon_to_en(a["lat"], a["lon"]) for a in anchors])  # type: ignore[arg-type]
    # Confirmed axis convention: East = scene X, North = -scene Z (see module docstring).
    X = np.array([[a["scene_xz"][0], -a["scene_xz"][1]] for a in anchors])  # type: ignore[index]

    n = len(X)
    mu_x, mu_y = X.mean(axis=0), Y.mean(axis=0)
    Xc, Yc = X - mu_x, Y - mu_y
    var_x = (Xc**2).sum() / n
    sigma_xy = (Yc.T @ Xc) / n
    U, D, Vt = np.linalg.svd(sigma_xy)
    S = np.eye(2)
    if np.linalg.det(U) * np.linalg.det(Vt.T) < 0:
        S[-1, -1] = -1
    R = U @ S @ Vt
    scale = float(np.trace(np.diag(D) @ S) / var_x)
    t = mu_y - scale * (R @ mu_x)

    pred = (scale * (X @ R.T)) + t
    residuals = np.linalg.norm(pred - Y, axis=1)
    rms = float(math.sqrt((residuals**2).mean()))
    per_anchor = {str(a["name"]): float(r) for a, r in zip(anchors, residuals)}

    return SiteTransform(
        scale=scale,
        rotation_matrix=((float(R[0, 0]), float(R[0, 1])), (float(R[1, 0]), float(R[1, 1]))),
        translation_m=(float(t[0]), float(t[1])),
        ref_lat=ref_lat,
        ref_lon=ref_lon,
        rms_residual_m=rms,
        per_anchor_residuals_m=per_anchor,
    )
