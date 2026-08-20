import { chromium } from 'playwright'

const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] })
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } })
const errs = []
page.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()) })
page.on('pageerror', (e) => errs.push('pageerror: ' + e.message))

await page.goto('http://localhost:5173/', { waitUntil: 'networkidle' })
await page.waitForSelector('[data-testid="terrain-provenance"]', { timeout: 20000 })
await page.waitForTimeout(2000)

const canvas = page.locator('canvas')
const box = await canvas.boundingBox()
for (let i = 0; i < 34; i += 1) {
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.wheel(0, -120)
  await page.waitForTimeout(40)
}
const cx = box.x + box.width / 2
const cy = box.y + box.height / 2
await page.mouse.move(cx, cy)
await page.mouse.down()
await page.mouse.move(cx + 15, cy - 30, { steps: 20 })
await page.mouse.up()
await page.waitForTimeout(500)

// Advance to hour 24 (the fixture's peak, and the hour the trigger targets).
await page.waitForSelector('[data-testid="hour-scrubber"]', { timeout: 20000 })
await page.click('[data-testid="hour-next"]') // 12 -> 24
await page.waitForTimeout(500)

console.log('provenance BEFORE assimilation:', await page.textContent('[data-testid="terrain-provenance"]'))
await page.screenshot({ path: '/tmp/envelope_before.png' })

// Trigger the real WS broadcast (fixture server, standing in for Stage 2's
// real /ws/site/{site_id} — see verify_fixture_server.py's own docstring).
const triggerResp = await fetch('http://127.0.0.1:8765/trigger-assimilation/vit-vellore?hour=24', {
  method: 'POST',
})
console.log('trigger response:', await triggerResp.json())

await page.waitForTimeout(250) // catch the pulse near its start
console.log('provenance DURING pulse:', await page.textContent('[data-testid="terrain-provenance"]'))
await page.screenshot({ path: '/tmp/envelope_pulse.png' })

await page.waitForTimeout(1800) // let the pulse fully fade
console.log('provenance AFTER pulse:', await page.textContent('[data-testid="terrain-provenance"]'))
await page.screenshot({ path: '/tmp/envelope_after.png' })

console.log('canvas present:', await page.locator('canvas').count())
console.log('console errors:', errs.length ? errs.slice(0, 10) : 'none')
await browser.close()
