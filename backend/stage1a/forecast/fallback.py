"""Stage 1A's regional forecast source chain (T1A.4, revised).

GENCAST REMOVED (2026-08-19, explicit human decision)
--------------------------------------------------------
The legacy GenCast live-inference path — and its synthetic-fixture
fallback — has been deleted outright, not just deprioritised. The human
running this project has no TPU/JAX access or GenCast credentials and never
will for this build; keeping a code path that can only ever raise
`GenCastUnavailableError` added weight without ever doing anything. If
GenCast access becomes available later, `client.py`/`parser.py`'s deleted
content (see git history — module was `gencast/`, git-mv'd to `forecast/`
first, in a commit right before this one) documents the confirmed real
GenCast/WeatherNext calling convention and can be restored as a new link in
the chain below.

CURRENT CHAIN (GEFS made real 2026-08-20 — see gefs/client.py)
--------------------------------------------------------------
    1. GEFS                (gefs.client — REAL, live, 0.25deg, 31 members)
    2. WeatherNext 2 Mini  (wn2mini — real, confirmed-working, manual export)

Order is an explicit human decision, not a default: GEFS is fully automated
with no manual step, while WeatherNext 2 Mini requires a human to run a
Colab notebook ahead of time. As of the 2026-08-20 amendment GEFS is also
the more accurate input for Stage 1B's downscaling — 0.25deg (~27.75km)
native resolution vs WN2 Mini's 1.0deg (~111km), which is the stated
reason the project owner asked for the switch.

If neither link produces a forecast, `get_regional_forecast` raises
`NoRegionalForecastAvailableError` — never fabricates a result.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from stage1a.config import Stage1ASettings, get_settings
from stage1a.forecast.errors import NoRegionalForecastAvailableError
from stage1a.forecast.provenance import ForecastPath, ForecastProvenance, RegionalForecastResult
from stage1a.gefs.client import fetch_gefs_forecast
from stage1a.gefs.errors import GEFSUnavailableError
from stage1a.shared.contracts import BoundingBox
from stage1a.wn2mini.errors import WN2ForecastUnavailableError
from stage1a.wn2mini.loader import load_wn2_mini_forecast
from stage1a.wn2mini.parser import parse_wn2_mini_output

logger = logging.getLogger(__name__)


def _try_wn2_mini(
    bbox: BoundingBox,
    forecast_start: datetime,
    settings: Stage1ASettings,
) -> RegionalForecastResult:
    """Load and parse the manually-exported WeatherNext 2 Mini file.

    Raises:
        WN2ForecastUnavailableError: if no file exists at the configured
            path — propagated to the caller so it can try the next link.
        wn2mini.errors.WN2ParseError: if the file exists but is malformed.
            NOT caught here — a broken export is a real bug, not something
            to silently fall through on.
    """
    dataset = load_wn2_mini_forecast(settings.wn2_mini_forecast_path)
    forecast = parse_wn2_mini_output(dataset, bbox, forecast_start)
    return RegionalForecastResult(
        forecast=forecast,
        provenance=ForecastProvenance(
            path=ForecastPath.WN2_MINI,
            retrieved_at=datetime.now(timezone.utc),
            source_file=str(settings.wn2_mini_forecast_path),
            synthetic=False,
        ),
    )


def get_regional_forecast(
    bbox: BoundingBox,
    forecast_start: datetime,
    settings: Optional[Stage1ASettings] = None,
) -> RegionalForecastResult:
    """Return the regional forecast, trying each source in the chain in order.

    Chain: GEFS -> WeatherNext 2 Mini. See the module docstring for why
    this order, and why there is nothing further.

    Only each link's own "unavailable" error advances to the next link. A
    parse failure or any other error propagates immediately — a source that
    exists but is malformed is a real bug, not a reason to quietly serve a
    different one.

    Raises:
        NoRegionalForecastAvailableError: if every link in the chain is
            exhausted.
    """
    settings = settings or get_settings()

    try:
        return fetch_gefs_forecast(bbox, forecast_start, settings)
    except GEFSUnavailableError as exc:
        logger.info("%s Trying WeatherNext 2 Mini next.", exc)

    try:
        return _try_wn2_mini(bbox, forecast_start, settings)
    except WN2ForecastUnavailableError as exc:
        logger.warning("%s No further source to try.", exc)
        raise NoRegionalForecastAvailableError(
            "No regional forecast is available: no published GEFS cycle "
            "could be reached, and "
            f"WeatherNext 2 Mini has no export at "
            f"{settings.wn2_mini_forecast_path}. Run wn2_demo.ipynb in Colab "
            "and copy the result there."
        ) from exc
