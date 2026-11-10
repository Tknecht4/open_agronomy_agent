import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const legalName = /^(licen[cs]e|copying|notice)([.\-_]|$)/i

function legalFiles(directory) {
  return fs.readdirSync(directory, { withFileTypes: true })
    .filter((entry) => legalName.test(entry.name) && entry.isFile())
    .map((entry) => entry.name)
    .sort()
}

export function dependencyNotices(frontendRoot) {
  const lock = JSON.parse(fs.readFileSync(path.join(frontendRoot, 'package-lock.json'), 'utf8'))
  if (lock.lockfileVersion !== 3 || !lock.packages) throw new Error('A v3 package lock is required')
  const selected = Object.entries(lock.packages)
    .filter(([name, record]) => name && (!record.dev || name === 'node_modules/vite'))
    .sort(([a], [b]) => a.localeCompare(b, 'en'))
  const sections = ['Bundled frontend dependency copyright and licence notices.',
    'Includes locked production packages and Vite helpers; some packages may be removed by tree shaking.',
    'Each package retains its own terms. Project licensing does not replace these notices.']
  for (const [packagePath, record] of selected) {
    if (!packagePath.startsWith('node_modules/') || packagePath.includes('\\')
      || packagePath.split('/').some((part) => !part || part === '.' || part === '..')) {
      throw new Error(`Unsafe locked package path: ${packagePath}`)
    }
    const directory = path.join(frontendRoot, packagePath)
    if (!fs.existsSync(directory) && record.optional) continue
    if (!fs.existsSync(path.join(directory, 'package.json'))) throw new Error(`Missing locked package: ${packagePath}`)
    const installed = JSON.parse(fs.readFileSync(path.join(directory, 'package.json'), 'utf8'))
    if (installed.version !== record.version) throw new Error(`Locked version mismatch: ${packagePath}`)
    const files = legalFiles(directory)
    if (!files.some((name) => /^(licen[cs]e|copying)([.\-_]|$)/i.test(name))) {
      throw new Error(`Missing full licence text: ${packagePath}`)
    }
    sections.push(`\n${'='.repeat(72)}\n${installed.name}@${installed.version}\nPackage: ${packagePath}\nDeclared licence: ${record.license || 'See original texts below'}`)
    for (const name of files) {
      const text = fs.readFileSync(path.join(directory, name), 'utf8').replaceAll('\r\n', '\n')
      if (!text.trim()) throw new Error(`Empty licence or notice: ${packagePath}/${name}`)
      sections.push(`\n--- ${name} ---\n\n${text.trimEnd()}`)
    }
  }
  return `${sections.join('\n')}\n`
}

export function writeLicenseNotices(frontendRoot, output) {
  const repositoryRoot = path.dirname(frontendRoot)
  const files = {
    'THIRD_PARTY_LICENSES.txt': dependencyNotices(frontendRoot),
    'LICENSE.txt': fs.readFileSync(path.join(repositoryRoot, 'LICENSE'), 'utf8'),
    'NOTICE.txt': fs.readFileSync(path.join(repositoryRoot, 'NOTICE'), 'utf8'),
  }
  fs.mkdirSync(output, { recursive: true })
  for (const [name, text] of Object.entries(files)) fs.writeFileSync(path.join(output, name), text)
  return Object.keys(files)
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
  const files = writeLicenseNotices(frontendRoot, path.join(frontendRoot, 'dist'))
  process.stdout.write(`Included licence notices: ${files.join(', ')}\n`)
}
