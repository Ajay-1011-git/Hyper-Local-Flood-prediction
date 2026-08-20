import { chromium } from 'playwright'

const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] })
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } })
const errs = []
page.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()) })
page.on('pageerror', (e) => errs.push('pageerror: ' + e.message))

// Landing page
await page.goto('http://localhost:5173/', { waitUntil: 'networkidle' })
await page.waitForTimeout(1000)
await page.screenshot({ path: '/tmp/pixel_landing.png' })
console.log('landing title:', await page.title())

// Dashboard (restyled overlays)
await page.goto('http://localhost:5173/dashboard', { waitUntil: 'networkidle' })
await page.waitForSelector('[data-testid="terrain-provenance"]', { timeout: 20000 })
await page.waitForTimeout(2000)
await page.screenshot({ path: '/tmp/pixel_dashboard.png' })

// Citizen / About placeholders
await page.goto('http://localhost:5173/citizen', { waitUntil: 'networkidle' })
await page.waitForTimeout(500)
await page.screenshot({ path: '/tmp/pixel_citizen_placeholder.png' })

await page.goto('http://localhost:5173/about', { waitUntil: 'networkidle' })
await page.waitForTimeout(500)
await page.screenshot({ path: '/tmp/pixel_about_placeholder.png' })

console.log('console errors:', errs.length ? errs.slice(0, 15) : 'none')
await browser.close()
