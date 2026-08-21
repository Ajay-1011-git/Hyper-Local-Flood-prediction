/**
 * Animated flow material for the water surface.
 *
 * ANIMATION SITS ON TOP OF REAL DATA — IT NEVER INVENTS ANY
 * ---------------------------------------------------------------
 * Every quantity that decides what you see is real, backend-computed
 * output from Stage 2's GNN + numerical solver, supplied per-vertex as
 * geometry attributes:
 *
 *   - vertex HEIGHT  -> real `NodeState.depth_mean_m` (already applied to
 *     the geometry's `position` by `waterGeometry.applyDepths`)
 *   - `aDepth`       -> the same real depth, used for colour and opacity
 *   - `aVelocity`    -> real `NodeState.velocity_mean_mps`, used for the
 *     ripple amplitude and how fast the flow bands travel
 *
 * `uTime` is the ONLY input that isn't simulation output, and it drives
 * nothing but the phase of the motion. Freeze it and you are left with
 * exactly the real depth field this project already rendered — the
 * animation makes real flow legible, it does not add information.
 *
 * WHY `onBeforeCompile` RATHER THAN A FULL CUSTOM ShaderMaterial
 * ---------------------------------------------------------------
 * Keeps three.js's own real physical lighting/fog/tonemapping chunks
 * (this scene has real directional + hemisphere lights that the water has
 * to sit under convincingly) instead of reimplementing them by hand.
 * Only the two chunks that actually need to change are patched.
 *
 * DRY CELLS RENDER FULLY TRANSPARENT
 * ---------------------------------------------------------------
 * The water grid spans the whole site, including cells with zero real
 * depth. Alpha is driven from `aDepth`, so dry ground shows no water at
 * all rather than a site-wide sheet sitting at ground level — the same
 * honesty point `WaterSurface`'s own docstring already makes about not
 * rendering a fabricated flat sheet.
 */

import * as THREE from 'three'

export interface FlowMaterialHandle {
  material: THREE.MeshPhysicalMaterial
  /** Advance the animation. Call from `useFrame` with real elapsed seconds. */
  setTime: (seconds: number) => void
}

/** Depth (m) at which the water reads as fully "deep" for colouring. */
const DEEP_M = 0.8

export function createFlowMaterial(): FlowMaterialHandle {
  const uTime = { value: 0 }

  const material = new THREE.MeshPhysicalMaterial({
    color: '#2f6f9e',
    transparent: true,
    roughness: 0.15,
    metalness: 0,
    side: THREE.DoubleSide,
    polygonOffset: true,
    polygonOffsetFactor: -4,
    polygonOffsetUnits: -4,
  })

  material.onBeforeCompile = (shader) => {
    shader.uniforms.uTime = uTime

    shader.vertexShader =
      `
      attribute float aDepth;
      attribute float aVelocity;
      uniform float uTime;
      varying float vDepth;
      varying float vVelocity;
      varying vec2 vFlowXZ;
      ` +
      shader.vertexShader.replace(
        '#include <begin_vertex>',
        `
        #include <begin_vertex>
        vDepth = aDepth;
        vVelocity = aVelocity;
        vFlowXZ = position.xz;

        // Ripples only where there is real water, with an amplitude set
        // by the real local velocity: still water stays flat, fast water
        // visibly churns. Capped so the displacement can never be
        // mistaken for real depth (it is at most a couple of cm).
        float wet = step(0.005, aDepth);
        float amp = wet * clamp(aVelocity * 0.015, 0.0, 0.03);
        float phase = (position.x + position.z) * 1.1 - uTime * (1.2 + aVelocity * 3.0);
        transformed.y += sin(phase) * amp;
        `,
      )

    shader.fragmentShader =
      `
      uniform float uTime;
      varying float vDepth;
      varying float vVelocity;
      varying vec2 vFlowXZ;
      ` +
      shader.fragmentShader.replace(
        '#include <color_fragment>',
        `
        #include <color_fragment>

        float d = clamp(vDepth / ${DEEP_M.toFixed(1)}, 0.0, 1.0);
        vec3 shallow = vec3(0.42, 0.72, 0.85);
        vec3 deep    = vec3(0.04, 0.17, 0.40);
        vec3 water   = mix(shallow, deep, d);

        // Flow bands travelling across the surface. Their speed is the
        // real local velocity, so where the solver says water moves
        // faster, the streaks visibly move faster.
        float bands = sin((vFlowXZ.x + vFlowXZ.y) * 0.9 - uTime * (0.8 + vVelocity * 4.0));
        float streak = smoothstep(0.72, 1.0, bands) * clamp(vVelocity * 1.6, 0.0, 1.0);
        water += streak * 0.30;

        diffuseColor.rgb = water;
        `,
      )

    // Alpha from real depth: nothing at all where the site is genuinely
    // dry, rising to a solid-but-still-translucent surface once there is
    // real standing water.
    shader.fragmentShader = shader.fragmentShader.replace(
      '#include <alphamap_fragment>',
      `
      #include <alphamap_fragment>
      diffuseColor.a *= smoothstep(0.0, 0.05, vDepth) * 0.82;
      `,
    )
  }

  // Changing onBeforeCompile requires a program rebuild.
  material.needsUpdate = true

  return {
    material,
    setTime: (seconds: number) => {
      uTime.value = seconds
    },
  }
}
