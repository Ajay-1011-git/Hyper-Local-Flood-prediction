"""Hazard extraction — T3.1.

Not yet implemented — blocked on the real SimulationResult/NodeState
shape (see CLAUDE.md's "STOP" section; backend/shared/contracts.py's
current definitions are a reconstructed, unconfirmed draft).

Will implement `extract_peak_hazard(sim_result: SimulationResult,
node_ids: List[str]) -> dict`, returning per requested node: peak depth,
peak velocity, peak rate-of-rise across the 72h window, the hour each
peak occurred, and ensemble_agreement_fraction at that peak. Must not
average away the peak.
"""
