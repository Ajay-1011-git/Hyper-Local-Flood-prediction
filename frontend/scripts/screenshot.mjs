import { chromium } from 'playwright'
const browser = await chromium.launch({ args: ['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader'] })
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } })
const errs = []
page.on('console', m => { if (m.type()==='error') errs.push(m.text()) })
page.on('pageerror', e => errs.push('pageerror: '+e.message))

for (const [name, url] of [['shaded','http://localhost:5173/dashboard'],['wireframe','http://localhost:5173/dashboard?wireframe=1']]) {
  await page.goto(url, { waitUntil: 'networkidle' })
  await page.waitForSelector('[data-testid="terrain-provenance"]', { timeout: 20000 })
  await page.waitForTimeout(2500)
  await page.screenshot({ path: `/tmp/terrain_${name}.png` })
  console.log(name, 'captured')
}
console.log('provenance text:', await page.textContent('[data-testid="terrain-provenance"]'))
console.log('canvas present:', await page.locator('canvas').count())
console.log('console errors:', errs.length ? errs.slice(0,5) : 'none')
await browser.close()
