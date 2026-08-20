import { chromium } from 'playwright'
const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] })
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } })
const errs = []
page.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()) })
page.on('pageerror', (e) => errs.push('pageerror: ' + e.message))

await page.goto('http://localhost:5173/', { waitUntil: 'networkidle' })
await page.waitForSelector('[data-testid="terrain-provenance"]', { timeout: 20000 })
// Let the terrain + site mesh both load and the water/lighting settle.
await page.waitForTimeout(3000)
await page.screenshot({ path: '/tmp/site_mesh_wide.png' })

// Zoom in closer to the buildings by dispatching wheel events over the canvas.
const canvas = page.locator('canvas')
const box = await canvas.boundingBox()
for (let i = 0; i < 18; i += 1) {
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.wheel(0, -120)
  await page.waitForTimeout(60)
}
await page.waitForTimeout(500)
await page.screenshot({ path: '/tmp/site_mesh_close.png' })

console.log('provenance text:', await page.textContent('[data-testid="terrain-provenance"]'))
console.log('canvas present:', await page.locator('canvas').count())
console.log('console errors:', errs.length ? errs.slice(0, 10) : 'none')
await browser.close()
