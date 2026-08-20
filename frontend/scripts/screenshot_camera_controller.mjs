import { chromium } from 'playwright'

const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] })
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } })
const errs = []
page.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()) })
page.on('pageerror', (e) => errs.push('pageerror: ' + e.message))

await page.goto('http://localhost:5173/dashboard', { waitUntil: 'networkidle' })
await page.waitForSelector('[data-testid="terrain-provenance"]', { timeout: 20000 })
await page.waitForSelector('[data-testid="fly-camera"]', { timeout: 20000 })
await page.waitForTimeout(1500)

console.log('button label BEFORE:', await page.textContent('[data-testid="fly-camera"]'))
await page.screenshot({ path: '/tmp/camera_00_wide_start.png' })

// Fire the real ~2s fly-in and capture it MID-TRANSITION, not just
// start/end -- this is what T4B.8's own VERIFY explicitly asks for.
await page.click('[data-testid="fly-camera"]')

const frameTimes = [150, 450, 900, 1400, 1900, 2400]
for (const t of frameTimes) {
  await page.waitForTimeout(t === frameTimes[0] ? t : t - frameTimes[frameTimes.indexOf(t) - 1])
  const progressText = await page.textContent('[data-testid="fly-progress"]').catch(() => null)
  console.log(`t=${t}ms progress:`, progressText)
  await page.screenshot({ path: `/tmp/camera_${String(t).padStart(4, '0')}ms.png` })
}

console.log('button label AFTER:', await page.textContent('[data-testid="fly-camera"]'))

console.log('canvas present:', await page.locator('canvas').count())
console.log('console errors:', errs.length ? errs.slice(0, 10) : 'none')
await browser.close()
