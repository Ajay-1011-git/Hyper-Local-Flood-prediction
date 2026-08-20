/**
 * About / Methodology (`/about`) — T4C.6.
 *
 * Per User Flow §3.7: "a deliberate product decision, not documentation
 * filler... where the system's honesty principles (Architecture §9)
 * become something a visitor can actually read." Every fact below is
 * transcribed from this project's own real docs/code (architecture §9,
 * Stage 1A's CLAUDE.md, Terrain.tsx's docstring, fragility_curve.py's
 * real citations) — nothing here is filler or invented for the page.
 *
 * REQUIRED HONESTY STATEMENTS (all present as real, readable text below,
 * not just referenced):
 *   1. Rainfall isn't resolved below ~2km.
 *   2. The site terrain is DEM-interpolated, not surveyed.
 *   3. The live sensor demonstrates assimilation, not forecast
 *      improvement.
 *   4. The vulnerability curve is a general, cited approximation, not
 *      locally calibrated.
 *   5. Which forecast source (GEFS vs. WeatherNext 2 Mini) is powering
 *      the CURRENT display — fetched live below, never a static claim.
 */

import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { fetchRegionalForecast, queryKeys } from '../api/client'
import { forecastSourceLabel } from '../forecastSources'
import PixelPanel from '../components/pixel/PixelPanel'

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <PixelPanel style={{ padding: '1.25rem', marginBottom: '1.25rem' }}>
      <h2 className="font-pixel-body" style={{ fontSize: '1.4rem', margin: '0 0 0.75rem', color: 'var(--pixel-amber)' }}>
        {title}
      </h2>
      <div className="font-pixel-body" style={{ fontSize: '1.15rem', lineHeight: 1.6, color: 'var(--ops-text)' }}>
        {children}
      </div>
    </PixelPanel>
  )
}

function ExternalLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer" style={{ color: 'var(--pixel-accent)' }}>
      {children}
    </a>
  )
}

export function About() {
  const {
    data: regionalForecast,
    error: regionalError,
    isPending: regionalPending,
  } = useQuery({
    queryKey: queryKeys.regionalForecast,
    queryFn: fetchRegionalForecast,
    staleTime: Infinity,
    retry: false,
  })

  return (
    <main style={{ background: 'var(--pixel-bg-0)', color: 'var(--ops-text)', minHeight: '100vh' }} className="font-sans">
      <div style={{ maxWidth: 760, margin: '0 auto', padding: '2rem 1.25rem' }}>
        <Link to="/" className="font-pixel-body" style={{ color: 'var(--pixel-accent)', fontSize: '1.1rem' }}>
          ◂ Flood Watch
        </Link>
        <h1 className="font-pixel-display" style={{ fontSize: '1.3rem', margin: '1rem 0 0.5rem' }}>
          About &amp; Methodology
        </h1>
        <p className="font-pixel-body" style={{ fontSize: '1.2rem', color: 'var(--ops-text-dim)', marginBottom: '1.5rem' }}>
          Most flood-tech demos hide their limitations. This one publishes them.
        </p>

        {/* 5. Which forecast source is powering the CURRENT display —
            fetched live, never a static/hardcoded claim. */}
        <Section title="What's powering this display right now">
          {regionalPending && <p>Checking the live regional forecast source…</p>}
          {regionalError && (
            <p style={{ color: 'var(--sev-critical)' }}>
              The regional forecast is unavailable right now, so no source is currently live.
            </p>
          )}
          {regionalForecast && (
            <p data-testid="live-forecast-source">
              Right now, this system's regional rainfall forecast is coming from{' '}
              <strong>{forecastSourceLabel(regionalForecast.source)}</strong>, an ensemble of{' '}
              {regionalForecast.members.length} real member{regionalForecast.members.length === 1 ? '' : 's'}.
              GEFS (0.25°, ~28km) is the primary source; WeatherNext 2 Cyclones Mini (1.0°, ~111km) is the
              automatic fallback if GEFS is unavailable when a forecast is requested. There is no third
              fallback — if both are unreachable, the system reports an error rather than guessing.
            </p>
          )}
        </Section>

        <Section title="What this system does and does not claim">
          <ul style={{ margin: 0, paddingLeft: '1.3rem' }}>
            <li style={{ marginBottom: '0.6rem' }}>
              <strong>Rainfall is never claimed below about 2km resolution.</strong> The regional weather
              models this system uses (GEFS, WeatherNext 2) physically cannot resolve rainfall variation
              finer than that. Instead of pretending otherwise, we downscale the regional forecast
              statistically to your local area, then run a physical hydraulic simulation on a detailed
              local terrain model to translate that into street-level water depth.
            </li>
            <li style={{ marginBottom: '0.6rem' }}>
              <strong>Every prediction is ensemble-valued, not a single number presented as fact</strong> —
              from the regional rainfall forecast through the final damage ranking, every stage reports a
              distribution and a real agreement fraction, never one deterministic figure.
            </li>
            <li style={{ marginBottom: '0.6rem' }}>
              <strong>Physics and rendering are strictly separated.</strong> The 3D scene displays
              precomputed hydraulic values; it performs zero simulation of its own.
            </li>
            <li style={{ marginBottom: '0.6rem' }}>
              <strong>Buildings and roads are real physical constraints inside the simulation</strong>, not
              decorative geometry placed over a simulation that doesn't know they exist.
            </li>
            <li>
              <strong>Every stage degrades to a working fallback rather than failing silently</strong> — for
              example, the numerical solver stands in for the neural model if needed, so there is no failure
              mode that produces no usable output at all.
            </li>
          </ul>
        </Section>

        <Section title="How the forecast chain works">
          <ol style={{ margin: 0, paddingLeft: '1.3rem' }}>
            <li style={{ marginBottom: '0.6rem' }}>
              <strong>Regional rainfall ensemble.</strong> A continental-scale weather model produces dozens
              of possible 72-hour rainfall scenarios for the wider region.
            </li>
            <li style={{ marginBottom: '0.6rem' }}>
              <strong>River/reservoir cross-check.</strong> An independent government river-stage forecast
              (CWC) is checked against our own — a genuine second opinion, not a rubber stamp.
            </li>
            <li style={{ marginBottom: '0.6rem' }}>
              <strong>Local downscaling + physical simulation.</strong> The regional rainfall is scaled down
              using real local terrain, then a physical shallow-water simulation computes how that rainfall
              actually flows through the streets and buildings of the scanned site.
            </li>
            <li>
              <strong>Damage ranking.</strong> Hazard (how deep/fast the water gets), exposure (how big the
              structure is), and vulnerability (how much damage that depth/velocity typically causes) combine
              into a ranked list — never a single "this building will flood" claim.
            </li>
          </ol>
        </Section>

        <Section title="Data sources">
          <ul style={{ margin: 0, paddingLeft: '1.3rem' }}>
            <li style={{ marginBottom: '0.5rem' }}>
              <strong>GEFS</strong> (NOAA Global Ensemble Forecast System, 0.25°) —{' '}
              <ExternalLink href="https://nomads.ncep.noaa.gov/cgi-bin/filter_gefs_atmos_0p25s.pl">
                nomads.ncep.noaa.gov
              </ExternalLink>
              , our primary regional rainfall source.
            </li>
            <li style={{ marginBottom: '0.5rem' }}>
              <strong>WeatherNext 2 Cyclones Mini</strong> (Google DeepMind, 1.0°) —{' '}
              <ExternalLink href="https://github.com/google-deepmind/weathernext">
                github.com/google-deepmind/weathernext
              </ExternalLink>
              , our automatic fallback source.
            </li>
            <li style={{ marginBottom: '0.5rem' }}>
              <strong>CWC / India-WRIS</strong> river &amp; reservoir stage data —{' '}
              <ExternalLink href="https://nwdp.nwic.gov.in">nwdp.nwic.gov.in</ExternalLink>, our independent
              cross-check.
            </li>
            <li style={{ marginBottom: '0.5rem' }}>
              <strong>CartoDEM</strong> elevation data (ISRO Bhuvan) —{' '}
              <ExternalLink href="https://bhuvan.nrsc.gov.in/wiki/index.php/How_to_use_WMS_services">
                bhuvan.nrsc.gov.in
              </ExternalLink>
              , the regional terrain this system's rendering and downscaling are built on.
            </li>
            <li>
              <strong>Vulnerability / damage curve</strong> — USACE{' '}
              <ExternalLink href="https://planning.erdc.dren.mil/toolbox/library/EGMs/egm04-01.pdf">
                EGM 04-01
              </ExternalLink>{' '}
              (depth-damage baseline) combined with AIDR{' '}
              <ExternalLink href="https://knowledge.aidr.org.au/media/1891/guideline-7-3-technical-flood-risk-management.pdf">
                Guideline 7-3
              </ExternalLink>{' '}
              (velocity amplification).
            </li>
          </ul>
        </Section>

        {/* 2. Terrain honesty. */}
        <Section title="The site terrain is interpolated, not surveyed">
          <p style={{ margin: 0 }}>
            The 3D terrain you see is built from CartoDEM, a real elevation dataset at roughly 30-metre
            sampling — not a photogrammetry survey of the actual site. Over the ~300-metre scanned site
            patch, that is genuinely only about 10×10 real elevation samples; the smooth surface you see
            comes from ordinary interpolation between those real points, not synthesized detail beyond them.
            Where the raw data has real gaps (voids in the source raster), we show the patch's average
            elevation there and disclose the count — never a plausible-looking invented number.
          </p>
        </Section>

        {/* 3. Live sensor role. */}
        <Section title="What the live sensor actually proves">
          <p style={{ margin: 0 }}>
            The physical sensor unit (an HC-SR04 ultrasonic distance sensor on an ESP32, roughly ±0.5–1cm
            accuracy) demonstrates real-time <strong>data assimilation</strong> — when a real reading arrives,
            it narrows this system's uncertainty band around the current water level. It does{' '}
            <strong>not</strong> improve or feed into the underlying rainfall forecast itself; those are
            separate, independent mechanisms. In this deployment, a reading can come from the physical
            sensor or from the dashboard's "Simulate live reading" control — both update the system through
            the exact same real assimilation path, so the demonstration is honest either way.
          </p>
        </Section>

        {/* 4. Vulnerability curve honesty. */}
        <Section title="The vulnerability curve is a general approximation">
          <p style={{ margin: 0 }}>
            Structure damage estimates combine a published depth-damage curve (USACE EGM 04-01, for a
            one-story residential structure with no basement) with a published velocity-hazard
            classification (AIDR Guideline 7-3). Both are real, cited, general-purpose curves — neither has
            been locally calibrated to this specific site's actual building stock. Every damage estimate
            this system produces carries that same real, disclosed limitation.
          </p>
        </Section>

        <p className="font-data" style={{ fontSize: '0.85rem', color: 'var(--ops-text-dim)', marginTop: '2rem' }}>
          Transcribed from this project's own architecture documentation and source code — not marketing
          copy.
        </p>
      </div>
    </main>
  )
}

export default About
