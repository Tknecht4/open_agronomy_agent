import { describe, expect, it } from 'vitest'

import { repoRelativePath } from './BenchmarksRoute'


describe('benchmark artifact path portability', () => {
  it('keeps repository-relative paths', () => {
    expect(repoRelativePath('outputs/eval/gap-report.json')).toBe('outputs/eval/gap-report.json')
  })

  it('removes an arbitrary checkout prefix', () => {
    expect(repoRelativePath('/mnt/work/open_agronomy_agent/outputs/eval/gap-report.json')).toBe(
      'outputs/eval/gap-report.json',
    )
    expect(repoRelativePath('C:\\work\\open_agronomy_agent\\outputs\\eval\\gap-report.json')).toBe(
      'outputs/eval/gap-report.json',
    )
  })

  it('does not expose unrelated absolute parent directories', () => {
    expect(repoRelativePath('/private/state/gap-report.json')).toBe('gap-report.json')
    expect(repoRelativePath(undefined)).toBe('gap report pending')
  })
})
