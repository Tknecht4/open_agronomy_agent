import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { dependencyNotices, writeLicenseNotices } from './build-license-notices.mjs'

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

test('the real locked frontend ships complete upstream and project notices', () => {
  const output = fs.mkdtempSync(path.join(os.tmpdir(), 'open-agronomy-licences-'))
  try {
    const files = writeLicenseNotices(frontendRoot, output)
    const text = fs.readFileSync(path.join(output, 'THIRD_PARTY_LICENSES.txt'), 'utf8')
    assert.ok(text.includes('react@18.3.1'))
    assert.ok(text.includes('Copyright (c) Facebook, Inc. and its affiliates.'))
    assert.ok(text.includes('Permission is hereby granted, free of charge'))
    assert.ok(text.includes('leaflet@1.9.4'))
    assert.ok(text.includes('Redistribution and use in source and binary forms'))
    assert.ok(text.includes('vite@'))
    assert.equal(text, dependencyNotices(frontendRoot))
    for (const [target, source] of [['LICENSE.txt', 'LICENSE'], ['NOTICE.txt', 'NOTICE']]) {
      assert.equal(fs.readFileSync(path.join(output, target), 'utf8'),
        fs.readFileSync(path.join(frontendRoot, '..', source), 'utf8'))
    }
    assert.equal(files.length, 3)
  } finally { fs.rmSync(output, { recursive: true, force: true }) }
})

test('missing licence texts, absent required packages, and version drift fail closed', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'open-agronomy-licence-fixture-'))
  try {
    fs.writeFileSync(path.join(root, 'package-lock.json'), JSON.stringify({
      lockfileVersion: 3, packages: { 'node_modules/example': { version: '1.0.0', license: 'MIT' } },
    }))
    assert.throws(() => dependencyNotices(root), /Missing locked package/)
    const directory = path.join(root, 'node_modules/example')
    fs.mkdirSync(directory, { recursive: true })
    fs.writeFileSync(path.join(directory, 'package.json'), JSON.stringify({ name: 'example', version: '2.0.0' }))
    assert.throws(() => dependencyNotices(root), /Locked version mismatch/)
    fs.writeFileSync(path.join(directory, 'package.json'), JSON.stringify({ name: 'example', version: '1.0.0' }))
    assert.throws(() => dependencyNotices(root), /Missing full licence text/)
  } finally { fs.rmSync(root, { recursive: true, force: true }) }
})
