"""GenCast inference client (T1A.2).

DOCUMENTATION CONSULTED IN-SESSION (anti-hallucination rule 1)
--------------------------------------------------------------
Nothing below is recalled from memory. The calling convention was confirmed
against these sources, fetched during this session:

* https://github.com/google-deepmind/graphcast
    — states GenCast is published as "WeatherNext Gen" and points to
      `docs/weathernext1_gen/README.md`; weights live in the `dm_graphcast`
      Google Cloud Bucket.
* https://raw.githubusercontent.com/google-deepmind/graphcast/main/docs/weathernext1_gen/README.md
    — the model lives in `gencast.py`, "Combines the GenCast model
      architecture, wrapped as a denoiser, with a sampler to generate
      predictions"; helpers in `utils/` (`rollout.py`, `normalization.py`,
      `autoregressive.py`); weights and statistics in the `gencast/` subdir
      of the bucket; demo notebook `gencast_mini_demo.ipynb`.
* https://raw.githubusercontent.com/google-deepmind/weathernext/master/docs/weathernext1_gen/gencast_mini_demo.ipynb
    — the real import and call sequence (reproduced in `_LIVE_INFERENCE_RECIPE`
      below); checkpoints under `gencast/params/`, example data under
      `gencast/dataset/`; output is an `xarray.Dataset` with a `sample`
      dimension for ensemble members.
* https://raw.githubusercontent.com/google-deepmind/weathernext/master/weathernext/weathernext1_gen/gencast.py
    — `class GenCast(predictor_base.Predictor)` with
      `__call__(self, inputs: xarray.Dataset, targets_template: xarray.Dataset,
      forcings: Optional[xarray.Dataset] = None, **kwargs) -> xarray.Dataset`;
      TASK `input_duration='24h'`; and explicitly: "GenCast predicts in 12hr
      timesteps" / "GenCast takes the current frame and the frame 12 hours
      prior".

FACTS THAT CONSTRAIN THE REST OF STAGE 1A
------------------------------------------
1. GenCast's native output type is `xarray.Dataset` — so that is what this
   function returns, unparsed. T1A.3 does the mapping.
2. Precipitation is carried as `total_precipitation_12hr`, accumulated over
   each 12-hour step. GenCast does NOT produce hourly rainfall.
3. Ensemble members are the `sample` dimension, produced by
   `rollout.chunked_prediction_generator_multiple_runs(..., num_samples=N)`.
4. `weathernext` is not on PyPI and inference needs JAX on TPU/GPU, so live
   inference cannot run on a machine without that stack. That is not an
   error condition to paper over — see `GenCastUnavailableError`.

WHERE TO PLUG IN REAL INFERENCE
--------------------------------
`_run_live_inference` is the single seam. It is the only function that needs
a body when a TPU/GPU host becomes available; everything downstream already
consumes `xarray.Dataset` and needs no change.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime
from typing import Final

import xarray as xr

from stage1a.config import Stage1ASettings, get_settings
from stage1a.gencast.errors import GenCastUnavailableError
from stage1a.shared.contracts import BoundingBox

# GenCast's fixed native characteristics, quoted from the sources above.
GENCAST_TIMESTEP_HOURS: Final[int] = 12
GENCAST_PRECIP_VARIABLE: Final[str] = "total_precipitation_12hr"
GENCAST_MEMBER_DIM: Final[str] = "sample"
GENCAST_NATIVE_RESOLUTION_KM: Final[float] = 28.0  # ~0.25 deg, per §B.2 default

# Reproduced verbatim from gencast_mini_demo.ipynb so a future implementer has
# the confirmed call sequence in front of them rather than guessing it.
_LIVE_INFERENCE_RECIPE: Final[str] = '''
from weathernext.utils import rollout, normalization, checkpoint, data_utils
from weathernext.weathernext1_gen import gencast, denoiser

predictor = gencast.GenCast(
    sampler_config=sampler_config,
    task_config=task_config,
    denoiser_architecture_config=denoiser_architecture_config,
    noise_config=noise_config,
    noise_encoder_config=noise_encoder_config,
)
predictor = normalization.InputsAndResiduals(predictor, ...)

chunks = []
for chunk in rollout.chunked_prediction_generator_multiple_runs(
    predictor_fn=run_forward_pmap,
    rngs=rngs,
    inputs=eval_inputs,
    targets_template=eval_targets * np.nan,
    forcings=eval_forcings,
    num_steps_per_chunk=1,
    num_samples=num_ensemble_members,
    pmap_devices=jax.local_devices(),
):
    chunks.append(chunk)
predictions = xarray.combine_by_coords(chunks)   # -> xarray.Dataset
'''


def _module_installed(name: str) -> bool:
    """Return True if `name` is importable without importing it."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def check_gencast_available(settings: Stage1ASettings | None = None) -> None:
    """Raise `GenCastUnavailableError` unless live inference could actually run.

    Checks the three things the confirmed documentation says are required:
    the `weathernext` package, a JAX runtime, and a configured source of
    published weights (local path or remote TPU endpoint). The error message
    names every missing piece so the caller — and the human — can see exactly
    what is absent rather than getting an opaque failure.
    """
    settings = settings or get_settings()
    missing: list[str] = []

    if not _module_installed("weathernext"):
        missing.append(
            "the `weathernext` package (GenCast's implementation; not on PyPI — "
            "install from https://github.com/google-deepmind/weathernext)"
        )
    if not _module_installed("jax"):
        missing.append("a JAX runtime (`jax`), required for TPU/GPU inference")
    if not settings.gencast_weights_path and not settings.gencast_tpu_endpoint:
        missing.append(
            "published weights: set GENCAST_WEIGHTS_PATH (checkpoints live under "
            "gencast/params/ in the `dm_graphcast` GCS bucket) or "
            "GENCAST_TPU_ENDPOINT for remote compute"
        )

    if missing:
        raise GenCastUnavailableError(
            "Live GenCast inference cannot run in this environment. Missing: "
            + "; ".join(missing)
            + ". Use the precomputed fallback (T1A.4) instead — do not "
            "substitute synthesised data."
        )


def _run_live_inference(bbox: BoundingBox, forecast_start: datetime) -> xr.Dataset:
    """Execute GenCast on the configured TPU/GPU host.

    IMPLEMENTATION SEAM. This is the one function to fill in once a TPU or
    GPU host is available; see `_LIVE_INFERENCE_RECIPE` for the confirmed
    call sequence and the module docstring for the sources it came from.

    It deliberately raises rather than returning anything: a stub that
    returned a plausible-looking Dataset would be fabricated model output,
    which §A forbids outright.
    """
    raise GenCastUnavailableError(
        "GenCast live inference is not implemented in this deployment. The "
        "environment checks passed, but `_run_live_inference` has no body yet "
        "— fill it in using the confirmed call sequence in "
        "`_LIVE_INFERENCE_RECIPE`. Until then the precomputed fallback (T1A.4) "
        "is the supported path."
    )


def run_gencast_inference(
    bbox: BoundingBox,
    forecast_start: datetime,
    settings: Stage1ASettings | None = None,
) -> xr.Dataset:
    """Run GenCast for `bbox` starting at `forecast_start`.

    Returns GenCast's native, unparsed output — an `xarray.Dataset` carrying
    a `sample` dimension over ensemble members and `total_precipitation_12hr`
    accumulated per 12-hour step. Converting that into the §B.2
    `RegionalEnsembleForecast` contract is T1A.3's job, not this one's.

    Raises:
        GenCastUnavailableError: if inference cannot run here. This is the
            expected outcome on any host without the GenCast stack and a
            TPU/GPU, and is what triggers T1A.4's fallback.
    """
    check_gencast_available(settings)
    return _run_live_inference(bbox, forecast_start)
