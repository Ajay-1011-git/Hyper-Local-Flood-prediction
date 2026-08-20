import { chromium } from 'playwright'

const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] })
const page = await browser.newPage({ viewport: { width: 1500, height: 950 } })
const errs = []
page.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()) })
page.on('pageerror', (e) => errs.push('pageerror: ' + e.message))

await page.goto('http://localhost:5173/dashboard', { waitUntil: 'load', timeout: 60000 })
await page.waitForSelector('[data-testid="risk-ranking-list"]', { timeout: 30000 })
await page.waitForTimeout(3000)
console.log('risk list text (early):', await page.textContent('[data-testid="risk-ranking-list"]'))
await page.waitForSelector('[data-testid^="risk-row-"]', { timeout: 60000 })

// Advance the timeline a bit so the hazard time series has a real
// non-zero current-hour marker to show.
await page.click('[data-testid="hour-next"]').catch((e) => console.log('hour-next click failed:', e.message))
await page.waitForTimeout(500)

const firstRow = page.locator('[data-testid^="risk-row-"]').first()
console.log('clicking row:', await firstRow.getAttribute('data-testid'))
await firstRow.click()
await page.waitForTimeout(1500)

console.log('url:', page.url())
console.log('thumbnail present:', await page.locator('[data-testid="structure-thumbnail"]').count())
console.log('chart present:', await page.locator('[data-testid="hazard-time-series-chart"]').count())
console.log('breakdown text:', await page.textContent('[data-testid="risk-breakdown"]').catch(() => 'MISSING'))

await page.screenshot({ path: '/tmp/site_detail_full.png' })
await page.locator('[data-testid="site-detail-panel"]').screenshot({ path: '/tmp/site_detail_panel_only.png' })

// Toggle "Include in alert" and confirm it sticks.
await page.click('[data-testid="include-in-alert-toggle"]')
await page.waitForTimeout(200)
console.log('toggle checked:', await page.isChecked('[data-testid="include-in-alert-toggle"]'))

console.log('console errors:', errs.length ? errs.slice(0, 20) : 'none')
await browser.close()
