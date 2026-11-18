import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'
import { evaluateAudit, productionNodes } from './audit-dependencies.mjs'

const policy = JSON.parse(fs.readFileSync(new URL('../dependency-audit-policy.json', import.meta.url)))
const now = new Date('2026-11-18T12:00:00Z')
const fixture = () => ({
  lock: { lockfileVersion: 3, packages: {
    '': { dependencies: { app: '1.0.0' } },
    'node_modules/app': { version: '1.0.0' },
    'node_modules/picomatch': { version: '4.0.7', dev: true },
    'node_modules/vite': { version: '8.3.6', dev: true, dependencies: { picomatch: '^4.0.0' } },
  } },
  report: { auditReportVersion: 2, vulnerabilities: {
    picomatch: { name: 'picomatch', severity: 'high', nodes: ['node_modules/picomatch'], via: [{
      name: 'picomatch', dependency: 'picomatch', severity: 'high', url: policy.advisory,
      source: 1247710,
    }] },
    vite: { name: 'vite', severity: 'high', nodes: ['node_modules/vite'], via: ['picomatch'] },
  }, metadata: { vulnerabilities: { info: 0, low: 0, moderate: 0, high: 2, critical: 0, total: 2 } } },
})
const evaluate = ({ report, lock }, options = {}) => evaluateAudit(report, lock, policy, { now, exitCode: 1, ...options })

test('the exact temporary dev finding stays visible, including its derived finding', () => {
  const result = evaluate(fixture())
  assert.equal(result.status, 'pass_with_temporary_dev_exception')
  assert.deepEqual(result.accepted_development_findings.sort(), ['picomatch', 'vite'])
  assert.equal(result.raw_vulnerability_counts.high, 2)
  assert.equal(result.exception_expires_at, '2026-11-24T00:00:00Z')
  assert.match(result.boundary, /not a vulnerability fix/)
})

test('production dependencies defeat a dev flag, including transitive reachability', () => {
  for (const direct of [true, false]) {
    const f = fixture()
    if (direct) f.lock.packages[''].dependencies.vite = '8.3.6'
    else f.lock.packages['node_modules/app'].dependencies = { vite: '8.3.6' }
    assert.equal(evaluate(f).status, 'fail')
    assert.ok(productionNodes(f.lock).has('node_modules/picomatch'))
  }
})

test('root peer dependencies also count as production reachability', () => {
  const f = fixture()
  f.lock.packages[''].peerDependencies = { picomatch: '4.0.7' }
  assert.ok(productionNodes(f.lock).has('node_modules/picomatch'))
  assert.equal(evaluate(f).status, 'fail')
})

test('a report cannot disguise a new package using an approved node path', () => {
  const f = fixture()
  f.report.vulnerabilities.unreviewed = { ...f.report.vulnerabilities.vite, name: 'unreviewed' }
  delete f.report.vulnerabilities.vite
  assert.throws(() => evaluate(f), /node and package identity disagree/)
})

test('a changed or unknown advisory source cannot borrow the approved URL', () => {
  for (const source of [999999, '1247710', undefined]) {
    const f = fixture()
    f.report.vulnerabilities.picomatch.via[0].source = source
    assert.equal(evaluate(f).status, 'fail')
  }
})

test('a non-development node or a changed locked version cannot use the exception', () => {
  for (const change of [item => { item.dev = false }, item => { item.version = '4.0.8' }]) {
    const f = fixture()
    change(f.lock.packages['node_modules/picomatch'])
    assert.equal(evaluate(f).status, 'fail')
  }
})

test('another advisory or an additional metavulnerability cause blocks CI', () => {
  for (const dependency of ['picomatch', 'vite']) {
    const f = fixture()
    f.report.vulnerabilities[dependency].via.push({ name: dependency, dependency,
      severity: 'high', url: 'https://github.com/advisories/GHSA-another-advisory' })
    assert.equal(evaluate(f).status, 'fail')
  }
})

test('critical severity cannot inherit a high-severity exception', () => {
  const f = fixture()
  f.report.vulnerabilities.picomatch.severity = 'critical'
  f.report.metadata.vulnerabilities.high = 1
  f.report.metadata.vulnerabilities.critical = 1
  assert.equal(evaluate(f).status, 'fail')
})

test('expiry, time before review, and unknown time block an exception', () => {
  for (const time of ['2026-11-24T00:00:00Z', '2026-11-16T00:00:00Z', 'invalid']) {
    assert.equal(evaluate(fixture(), { now: new Date(time) }).status, 'fail')
  }
})

test('missing causes and graph cycles are not implicitly covered', () => {
  for (const change of [
    f => { f.report.vulnerabilities.vite.via = ['unknown'] },
    f => { f.report.vulnerabilities.picomatch.via = ['vite'] },
  ]) {
    const f = fixture()
    change(f)
    assert.equal(evaluate(f).status, 'fail')
  }
})

test('malformed or transport-failed audit results never become a pass', () => {
  for (const change of [
    f => { f.report.error = { message: 'Registry unavailable' } },
    f => { f.report.auditReportVersion = 99 },
    f => { delete f.report.metadata },
    f => { f.report.metadata.vulnerabilities.total = 0 },
    f => { f.report.vulnerabilities.picomatch.via = [] },
    f => { f.report.vulnerabilities.picomatch.nodes = [] },
    f => { f.report.vulnerabilities.vite.nodes = ['node_modules/unreviewed'] },
  ]) {
    const f = fixture()
    change(f)
    assert.throws(() => evaluate(f))
  }
  for (const exitCode of [0, 2, null]) assert.throws(() => evaluate(fixture(), { exitCode }))
})

test('a clean audit needs no exception, even after the temporary policy expires', () => {
  const f = fixture()
  f.report.vulnerabilities = {}
  f.report.metadata.vulnerabilities = { info: 0, low: 0, moderate: 0, high: 0, critical: 0, total: 0 }
  const result = evaluate(f, { exitCode: 0, now: new Date('2026-12-01T00:00:00Z') })
  assert.equal(result.status, 'pass')
  assert.deepEqual(result.accepted_development_findings, [])
})

test('the inherited high threshold leaves a separate moderate finding visible', () => {
  const f = fixture()
  f.report.vulnerabilities.app = { name: 'app', severity: 'moderate', nodes: ['node_modules/app'],
    via: [{ name: 'app', dependency: 'app', severity: 'moderate', url: 'https://example.invalid/moderate' }] }
  f.report.metadata.vulnerabilities.moderate = 1
  f.report.metadata.vulnerabilities.total = 3
  const result = evaluate(f)
  assert.equal(result.status, 'pass_with_temporary_dev_exception')
  assert.equal(result.raw_vulnerability_counts.moderate, 1)
  assert.ok(!result.accepted_development_findings.includes('app'))
})

test('production resolution handles nested packages and fails on missing required dependencies', () => {
  const { lock } = fixture()
  lock.packages['node_modules/app'].dependencies = { inner: '1.0.0' }
  lock.packages['node_modules/app/node_modules/inner'] = { version: '1.0.0', dependencies: { picomatch: '4.0.7' } }
  assert.ok(productionNodes(lock).has('node_modules/picomatch'))
  delete lock.packages['node_modules/picomatch']
  assert.throws(() => productionNodes(lock), /Unresolved production dependency/)
})
