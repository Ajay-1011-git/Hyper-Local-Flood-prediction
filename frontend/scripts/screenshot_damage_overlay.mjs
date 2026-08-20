import { chromium } from 'playwright'

const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] })
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } })
const errs = []
page.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()) })
page.on('pageerror', (e) => errs.push('pageerror: ' + e.message))

await page.goto('http://localhost:5173/dashboard', { waitUntil: 'networkidle' })
await page.waitForSelector('[data-testid="terrain-provenance"]', { timeout: 20000 })
await page.waitForTimeout(1500)

const canvas = page.locator('canvas')
const box = await canvas.boundingBox()
for (let i = 0; i < 30; i += 1) {
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.wheel(0, -120)
  await page.waitForTimeout(35)
}
const cx = box.x + box.width / 2
const cy = box.y + box.height / 2
await page.mouse.move(cx, cy)
await page.mouse.down()
await page.mouse.move(cx + 15, cy - 30, { steps: 20 })
await page.mouse.up()
await page.waitForTimeout(500)

await page.waitForSelector('[data-testid="hour-scrubber"]', { timeout: 20000 })

// hour 12 (initial available hour) -- both structures still Monitoring
// (Building_01/Road_Segment_000's peak_hour=12 has JUST been reached;
// Building_02's peak_hour=48 is far off).
console.log('provenance at hour 12:', await page.textContent('[data-testid="terrain-provenance"]'))
await page.screenshot({ path: '/tmp/damage_hour_12.png' })

// hour 24 -- Building_01/Road_Segment_000 are now well past their real
// peak_hour=12: Building_01 -> Critical (red), Road_Network -> Warning
// (orange). Building_02's peak_hour=48 is still ahead -> stays Monitoring.
await page.click('[data-testid="hour-next"]')
await page.waitForTimeout(600)
console.log('provenance at hour 24:', await page.textContent('[data-testid="terrain-provenance"]'))
await page.screenshot({ path: '/tmp/damage_hour_24.png' })

// hour 48 -- Building_02 now also past its real peak_hour.
await page.click('[data-testid="hour-next"]')
await page.waitForTimeout(600)
await page.click('[data-testid="hour-next"]')
await page.waitForTimeout(600)
console.log('provenance at hour 48:', await page.textContent('[data-testid="terrain-provenance"]'))
await page.screenshot({ path: '/tmp/damage_hour_48.png' })

console.log('canvas present:', await page.locator('canvas').count())
console.log('console errors:', errs.length ? errs.slice(0, 10) : 'none')
await browser.close()
