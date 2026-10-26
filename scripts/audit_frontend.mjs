import { createRequire } from 'node:module'
import { mkdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { spawn } from 'node:child_process'

const root = resolve(import.meta.dirname, '..')
const require = createRequire(resolve(root, 'frontend/package.json'))
const { default: lighthouse } = await import(pathToFileURL(require.resolve('lighthouse')).href)
const chromeLauncher = await import(pathToFileURL(require.resolve('chrome-launcher')).href)
const playwrightModule = await import(pathToFileURL(require.resolve('playwright')).href)
const { chromium } = playwrightModule.default || playwrightModule
const server = spawn(process.execPath, [resolve(root, 'frontend/node_modules/vite/bin/vite.js'), 'preview', '--host', '127.0.0.1', '--port', '4173'], { cwd: resolve(root, 'frontend'), stdio: 'ignore' })
let chrome
try {
  for (let attempt = 0; attempt < 30; attempt++) {
    try { if ((await fetch('http://127.0.0.1:4173/preview')).ok) break } catch {}
    await new Promise(done => setTimeout(done, 250))
  }
  chrome = await chromeLauncher.launch({ chromePath: chromium.executablePath(), chromeFlags: ['--headless=new', '--disable-gpu', '--no-first-run'] })
  const result = await lighthouse('http://127.0.0.1:4173/preview', {
    port: chrome.port, output: ['json', 'html'], onlyCategories: ['performance', 'accessibility', 'best-practices'], logLevel: 'error',
  })
  mkdirSync(resolve(root, 'artifacts'), { recursive: true })
  writeFileSync(resolve(root, 'artifacts/lighthouse.json'), result.report[0])
  writeFileSync(resolve(root, 'artifacts/lighthouse.html'), result.report[1])
  const lhr = result.lhr
  const summary = { performance: lhr.categories.performance.score * 100, accessibility: lhr.categories.accessibility.score * 100,
    lcp_ms: Math.round(lhr.audits['largest-contentful-paint'].numericValue), cls: lhr.audits['cumulative-layout-shift'].numericValue,
    browser: lhr.environment.hostUserAgent, profile: 'Lighthouse default simulated mobile; production build; static mobile scene fallback' }
  console.log(JSON.stringify(summary, null, 2))
  if (summary.performance < 90 || summary.lcp_ms > 2500 || summary.cls > .1) process.exitCode = 1
} finally {
  if (chrome) await chrome.kill()
  server.kill()
}
