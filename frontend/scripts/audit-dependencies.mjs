import fs from 'node:fs'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath, pathToFileURL } from 'node:url'

const severities = new Set(['info', 'low', 'moderate', 'high', 'critical'])
const blocking = new Set(['high', 'critical'])
const requireValue = (condition, message) => {
  if (!condition) throw new Error(message)
}

// Resolve the actual lockfile graph independently of its dev flags. A package
// accidentally marked dev must not acquire an exception when production uses it.
export function productionNodes(lock) {
  requireValue(lock.lockfileVersion === 3 && lock.packages?.[''], 'Unsupported lockfile')
  const packages = lock.packages
  const resolve = (from, name) => {
    let current = from
    for (;;) {
      const candidate = `${current ? `${current}/` : ''}node_modules/${name}`
      if (packages[candidate]) return candidate
      if (!current) return null
      const index = current.lastIndexOf('/node_modules/')
      current = index < 0 ? '' : current.slice(0, index)
    }
  }
  const reached = new Set()
  const visit = (from, name, optional = false) => {
    const target = resolve(from, name)
    if (!target && optional) return
    requireValue(target, `Unresolved production dependency: ${from}:${name}`)
    if (reached.has(target)) return
    const item = packages[target]
    requireValue(!item.link && typeof item.version === 'string', `Unsupported production node: ${target}`)
    reached.add(target)
    walk(target, item)
  }
  const walk = (from, item) => {
    for (const name of Object.keys(item.dependencies ?? {})) visit(from, name)
    for (const name of Object.keys(item.optionalDependencies ?? {})) visit(from, name, true)
    for (const name of Object.keys(item.peerDependencies ?? {})) {
      visit(from, name, item.peerDependenciesMeta?.[name]?.optional === true)
    }
  }
  walk('', packages[''])
  return reached
}

export function evaluateAudit(report, lock, policy, { exitCode, now = new Date() }) {
  requireValue(report.auditReportVersion === 2 && !report.error, 'Unsupported or failed npm audit')
  requireValue(report.vulnerabilities && !Array.isArray(report.vulnerabilities), 'Missing audit graph')
  const graph = report.vulnerabilities
  const counts = report.metadata?.vulnerabilities
  requireValue(counts && counts.total === Object.keys(graph).length, 'Incomplete audit counts')
  for (const severity of severities) {
    requireValue(Number.isInteger(counts[severity]) && counts[severity] >= 0, 'Invalid audit counts')
    requireValue(counts[severity] === Object.values(graph).filter(v => v.severity === severity).length,
      'Audit severity counts disagree')
  }
  for (const [name, item] of Object.entries(graph)) {
    requireValue(item.name === name && severities.has(item.severity), 'Malformed vulnerability')
    requireValue(Array.isArray(item.via) && item.via.length && Array.isArray(item.nodes) && item.nodes.length,
      'Incomplete vulnerability paths')
    requireValue(item.nodes.every(node => typeof node === 'string'
      && node.endsWith(`node_modules/${name}`) && Object.hasOwn(lock.packages, node)
      && typeof lock.packages[node].version === 'string'), 'Audit node and package identity disagree')
  }
  const hasBlocking = Object.values(graph).some(v => blocking.has(v.severity))
  requireValue(exitCode === (hasBlocking ? 1 : 0), 'Audit process outcome disagrees with report')
  const production = productionNodes(lock)
  const reviewed = Date.parse(policy.reviewed_at)
  const expiry = Date.parse(policy.expires_at)
  const current = now.getTime()
  const exceptionCurrent = policy.schema_version === 1 && Number.isFinite(current)
    && Number.isInteger(policy.advisory_source) && policy.advisory_source > 0
    && Number.isFinite(reviewed) && Number.isFinite(expiry) && reviewed <= current && current < expiry
  const accepts = (name, visiting = new Set()) => {
    if (!exceptionCurrent || visiting.has(name)) return false
    const item = graph[name]
    if (!item || item.severity !== 'high') return false
    if (!item.nodes.every(node => lock.packages[node]?.dev === true && !production.has(node)
      && policy.development_nodes[node] === lock.packages[node].version)) return false
    const next = new Set(visiting).add(name)
    return item.via.every(cause => {
      if (typeof cause === 'string') return accepts(cause, next)
      return name === policy.affected_package && cause?.name === policy.affected_package
        && cause.dependency === policy.affected_package && cause.severity === 'high'
        && cause.url === policy.advisory
        && cause.source === policy.advisory_source
        && item.nodes.every(node => lock.packages[node].version === policy.affected_version)
    })
  }
  const findings = Object.entries(graph).filter(([, value]) => blocking.has(value.severity))
  const accepted = findings.filter(([name]) => accepts(name)).map(([name]) => name)
  const rejected = findings.filter(([name]) => !accepted.includes(name)).map(([name]) => name)
  return {
    status: rejected.length ? 'fail' : accepted.length ? 'pass_with_temporary_dev_exception' : 'pass',
    raw_vulnerability_counts: counts,
    accepted_development_findings: accepted,
    blocking_findings: rejected,
    exception_advisory: accepted.length ? policy.advisory : null,
    exception_expires_at: accepted.length ? policy.expires_at : null,
    production_nodes_checked: production.size,
    boundary: accepted.length ? policy.boundary : null,
  }
}

function main() {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
  const args = process.argv.slice(2)
  requireValue(args.length === 0 || (args.length === 2 && args[0] === '--report'), 'Expected --report <new-path>')
  const result = spawnSync(process.platform === 'win32' ? 'npm.cmd' : 'npm',
    ['audit', '--json', '--audit-level=high', '--include=dev'],
    { cwd: root, encoding: 'utf8', timeout: 120_000, maxBuffer: 16 * 1024 * 1024 })
  // Keep the original finding, including malformed output, rather than replacing
  // it with the accepted disposition. Exclusive publication prevents overwrites.
  if (args.length) fs.writeFileSync(args[1], result.stdout ?? '', { flag: 'wx' })
  requireValue(!result.error && result.signal === null, 'npm audit transport failed')
  const report = JSON.parse(result.stdout)
  const lock = JSON.parse(fs.readFileSync(path.join(root, 'package-lock.json'), 'utf8'))
  const policy = JSON.parse(fs.readFileSync(path.join(root, 'dependency-audit-policy.json'), 'utf8'))
  const summary = evaluateAudit(report, lock, policy, { exitCode: result.status })
  console.log(JSON.stringify(summary, null, 2))
  if (summary.status === 'fail') process.exitCode = 1
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try { main() } catch (error) {
    console.error(`Dependency audit failed: ${error.message}`)
    process.exitCode = 1
  }
}
