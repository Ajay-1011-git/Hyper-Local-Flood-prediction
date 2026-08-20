import { chromium } from 'playwright'

const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] })
const page = await browser.newPage({ viewport: { width: 1500, height: 950 } })
const errs = []
page.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()) })
page.on('pageerror', (e) => errs.push('pageerror: ' + e.message))

await page.goto('http://localhost:5173/dashboard', { waitUntil: 'networkidle' })
await page.waitForSelector('[data-testid="dashboard-topbar"]', { timeout: 20000 })
await page.waitForSelector('[data-testid="terrain-provenance"]', { timeout: 20000 })
await page.waitForTimeout(2500)
await page.screenshot({ path: '/tmp/dashboard_full.png' })

console.log('fan chart source:', await page.textContent('[data-testid="fan-chart-source"]').catch(() => 'MISSING'))
console.log('fan chart readout:', await page.textContent('[data-testid="fan-chart-readout"]').catch(() => 'MISSING'))
console.log('river stage card:', await page.textContent('[data-testid="river-stage-card"]').catch(() => 'MISSING'))
console.log('sensor strip:', await page.textContent('[data-testid="sensor-strip"]').catch(() => 'MISSING'))
console.log('risk ranking list:', await page.textContent('[data-testid="risk-ranking-list"]').catch(() => 'MISSING'))

// Cross-link: click the first real risk-ranking row.
const firstRow = page.locator('[data-testid^="risk-row-"]').first()
const rowTestId = await firstRow.getAttribute('data-testid')
console.log('clicking row:', rowTestId)
await firstRow.click()
await page.waitForTimeout(1500)
console.log('url after click:', page.url())
console.log('site-detail-panel present:', await page.locator('[data-testid="site-detail-panel"]').count())
await page.screenshot({ path: '/tmp/dashboard_site_detail.png' })

console.log('console errors:', errs.length ? errs.slice(0, 20) : 'none')
await browser.close()
