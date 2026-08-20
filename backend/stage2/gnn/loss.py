"""Hybrid loss: supervised + mass-conservation residual (T2.6).

REAL FORMULA, CONFIRMED — not invented for this project
------------------------------------------------------------
Adapted directly from RBTV1/mSWE-GNN's real `training/loss.py`
(`conservation_loss`, fetched in-session), simplified for this project's
single-graph (non-multiscale, non-batched) setting: the original computes
`sum(area * (pred_depth - input_depth)) - inflow_volume` and uses it as a
physics-residual term alongside a supervised RMSE/MAE loss — this IS the
project's own "hybrid loss (solver-supervised + physics-residual)"
requirement, already published and real, not something invented here.
`get_mean_error`'s RMSE option is reused the same way for the supervised
term. Not vendored verbatim (the original needs `Batch`/`node_ptr`/
`get_inflow_volume` multiscale-batching machinery this project doesn't
have) — reimplemented here for the single-graph case, with the exact same
physical formula.
"""

from __future__ import annotations


import torch

OUT_DIM = 2  # depth, velocity — see graph_builder.py


def supervised_rmse(preds: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    """RMSE across both water variables (depth, velocity), equally weighted.

    Simplification vs. the real repo's `loss_function`, which supports a
    `velocity_scaler` to weight the two variables differently — omitted
    here rather than guessing a scale factor with no basis.
    """
    diff = preds - target
    return torch.sqrt((diff**2).mean())


def mass_conservation_residual(
    pred_depth: torch.Tensor,
    input_depth: torch.Tensor,
    cell_area_m2: float,
    total_inflow_volume_m3: float,
) -> torch.Tensor:
    """Real formula from RBTV1/mSWE-GNN's `conservation_loss`, single-graph form.

    `sum(area * (pred_depth - input_depth))` is the model's own predicted
    volume change; it should equal the real water volume actually added
    this step (rainfall recharge, from T2.5's boundary condition). The
    absolute difference is the physics-residual term.
    """
    predicted_volume_change = (cell_area_m2 * (pred_depth - input_depth)).sum()
    return (predicted_volume_change - total_inflow_volume_m3).abs()


def hybrid_loss(
    preds: torch.Tensor,
    target: torch.Tensor,
    input_depth: torch.Tensor,
    cell_area_m2: float,
    total_inflow_volume_m3: float,
    conservation_weight: float = 0.1,
) -> torch.Tensor:
    """Supervised RMSE + weighted mass-conservation residual.

    `conservation_weight=0.1` is a starting default (the real repo's own
    `config.yaml` doesn't fix one universal value — it's tuned per
    experiment) — FLAG FOR HUMAN REVIEW/tuning, not independently verified
    optimal for this project's data.
    """
    pred_depth = preds[:, 0]
    supervised = supervised_rmse(preds, target)
    conservation = mass_conservation_residual(
        pred_depth, input_depth, cell_area_m2, total_inflow_volume_m3
    )
    # Normalise the (potentially large, m^3-scale) conservation residual
    # onto a comparable footing with the (metre-scale) supervised RMSE,
    # matching the real repo's own "/1e6" style normalisation intent
    # (there, for a much larger multiscale domain) -- here, scaled by cell
    # count instead, since this project's sites are orders of magnitude
    # smaller.
    return supervised + conservation_weight * conservation / max(pred_depth.numel(), 1)
