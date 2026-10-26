import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { gzipSync } from 'node:zlib'

const root = resolve(import.meta.dirname, '../frontend/dist')
const manifest = JSON.parse(readFileSync(resolve(root, '.vite/manifest.json'), 'utf8'))
const entry = Object.keys(manifest).find(key => manifest[key].isEntry)
const visited = new Set()
function walk(key) {
  if (visited.has(key)) return 0
  visited.add(key)
  const value = manifest[key]
  return gzipSync(readFileSync(resolve(root, value.file))).length + (value.imports || []).reduce((sum, item) => sum + walk(item), 0)
}
const bytes = walk(entry)
console.log(`Initial JavaScript (including all static imports): ${(bytes / 1024).toFixed(1)} KB gzip`)
if (bytes > 300 * 1024) throw new Error('Initial JavaScript exceeds the 300 KB budget')
if ([...visited].some(key => manifest[key].file.includes('scene-vendor'))) throw new Error('3D vendor code is eagerly loaded')
