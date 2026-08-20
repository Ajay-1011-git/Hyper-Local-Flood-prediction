import { chromium } from 'playwright'
const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] })
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } })
const errs = []
page.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()) })
page.on('pageerror', (e) => errs.push('pageerror: ' + e.message))

await page.goto('http://localhost:5173/', { waitUntil: 'networkidle' })
await page.waitForSelector('[data-testid="terrain-provenance"]', { timeout: 20000 })
await page.waitForTimeout(2500)

// Zoom in over the site so the water surface is clearly visible.
const canvas = page.locator('canvas')
const box = await canvas.boundingBox()
for (let i = 0; i < 24; i += 1) {
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.wheel(0, -120)
  await page.waitForTimeout(50)
}
// Small rotate toward a lower angle (OrbitControls: left-drag orbits) so
// the water's real vertical rise against the building walls reads clearly,
// without dragging so far the camera dips below the terrain.
const cx = box.x + box.width / 2
const cy = box.y + box.height / 2
await page.mouse.move(cx, cy)
await page.mouse.down()
await page.mouse.move(cx + 15, cy - 35, { steps: 20 })
await page.mouse.up()
await page.waitForTimeout(500)

await page.waitForSelector('[data-testid="hour-scrubber"]', { timeout: 20000 })
console.log('provenance text (hour 0):', await page.textContent('[data-testid="terrain-provenance"]'))
await page.screenshot({ path: '/tmp/water_hour_0.png' })

// Advance through the fixture's real hours (0, 12, 24, 36, 48) — the
// synthetic demo depth grows to hour 24, then recedes.
for (const label of ['hour_12', 'hour_24', 'hour_36', 'hour_48']) {
  await page.click('[data-testid="hour-next"]')
  await page.waitForTimeout(400)
  console.log(`provenance text (${label}):`, await page.textContent('[data-testid="terrain-provenance"]'))
  await page.screenshot({ path: `/tmp/water_${label}.png` })
}

console.log('canvas present:', await page.locator('canvas').count())
console.log('console errors:', errs.length ? errs.slice(0, 10) : 'none')
await browser.close()
