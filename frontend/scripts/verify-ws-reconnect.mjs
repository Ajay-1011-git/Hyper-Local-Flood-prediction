/**
 * T4B.1's own real VERIFY: connects a real SiteSocket (via a real
 * browser, driven by Playwright) to a REAL running Stage 2 backend, then
 * kills that backend process mid-test to force a genuine drop, and
 * confirms the client really reconnects once the backend comes back --
 * all captured from real browser console output, not simulated.
 */
import { chromium } from 'playwright'
import { execSync, spawn } from 'node:child_process'

const REPO_ROOT = new URL('../../', import.meta.url).pathname
const STAGE2_DIR = `${REPO_ROOT}backend`
const STAGE2_VENV_PY = `${REPO_ROOT}backend/stage2/.venv/bin/python`

function startStage2() {
  const proc = spawn(STAGE2_VENV_PY, ['-m', 'uvicorn', 'stage2.routes:app', '--port', '8765', '--log-level', 'error'], {
    cwd: STAGE2_DIR,
    stdio: 'ignore',
  })
  return proc
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

const browser = await chromium.launch()
const page = await browser.newPage()
const consoleLog = []
page.on('console', (m) => {
  const text = m.text()
  if (text.startsWith('[verify-ws]')) {
    const line = `${new Date().toISOString().slice(11, 23)} ${text}`
    consoleLog.push(line)
    console.log(line)
  }
})

console.log('--- loading verify-ws.html against the REAL Stage 2 backend (already running) ---')
await page.goto('http://localhost:5173/verify-ws.html', { waitUntil: 'networkidle' })
await page.waitForSelector('[data-status="open"]', { timeout: 10000 })
console.log('--- confirmed real "open" status ---')

console.log('--- killing the REAL Stage 2 backend process to force a genuine drop ---')
execSync("lsof -ti:8765 | xargs kill -9 || true")
await page.waitForSelector('[data-status="reconnecting"]', { timeout: 10000 })
console.log('--- confirmed real "reconnecting" status after the real drop ---')

console.log('--- waiting 4s with the backend down, to observe real failed reconnect attempts ---')
await sleep(4000)

console.log('--- restarting the REAL Stage 2 backend ---')
const restarted = startStage2()
await page.waitForSelector('[data-status="open"]', { timeout: 15000 })
console.log('--- confirmed real reconnection to "open" after the backend came back, no page reload ---')

await browser.close()
restarted.kill()

console.log('\n=== FULL console log, real, in order ===')
console.log(consoleLog.join('\n'))
