import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  PHASE6_IMAGE_INLINE_BASE64_BUDGET,
  PHASE6_IMAGE_TARGET_MAX_DIMENSION,
  PHASE6_IMAGE_TARGET_QUALITY,
  compressPhase6ImageInBrowser,
  preparePhase6ImageUpload,
} from './imageUploadPreparation'

describe('Phase 6 image upload preparation', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('normalizes data URLs and marks small images inside the inline budget', async () => {
    const prepared = await preparePhase6ImageUpload('data:image/png;base64, abc123 ')

    expect(prepared.base64Content).toBe('abc123')
    expect(prepared.contentType).toBe('image/png')
    expect(prepared.metadata).toMatchObject({
      schema_version: 'phase6.image_upload_preparation.v1',
      preserve_original: false,
      original_content_type: 'image/png',
      prepared_content_type: 'image/png',
      status: 'within_inline_budget',
      original_base64_chars: 6,
      prepared_base64_chars: 6,
      target_max_dimension_px: PHASE6_IMAGE_TARGET_MAX_DIMENSION,
      target_quality: PHASE6_IMAGE_TARGET_QUALITY,
    })
  })

  it('preserves oversized originals only when explicitly requested', async () => {
    const original = 'x'.repeat(PHASE6_IMAGE_INLINE_BASE64_BUDGET + 1)

    await expect(preparePhase6ImageUpload(original)).rejects.toThrow('preserve-original consent')

    const prepared = await preparePhase6ImageUpload(original, { preserveOriginal: true })

    expect(prepared.base64Content).toBe(original)
    expect(prepared.contentType).toBe('image/png')
    expect(prepared.metadata.status).toBe('preserved_original')
    expect(prepared.metadata.preserve_original).toBe(true)
  })

  it('uses an injected compressor for oversized uploads and rejects ineffective compression', async () => {
    const original = 'x'.repeat(20)
    const transform = vi.fn(async () => ({ base64Content: 'data:image/jpeg;base64,' + 'y'.repeat(8) }))

    const prepared = await preparePhase6ImageUpload(original, {
      maxInlineBase64Chars: 10,
      targetMaxDimension: 1024,
      targetQuality: 0.7,
      transform,
    })

    expect(transform).toHaveBeenCalledWith({
      base64Content: original,
      contentType: 'image/png',
      targetMaxDimension: 1024,
      targetQuality: 0.7,
    })
    expect(prepared.base64Content).toBe('y'.repeat(8))
    expect(prepared.contentType).toBe('image/jpeg')
    expect(prepared.metadata).toMatchObject({
      status: 'compressed',
      original_content_type: 'image/png',
      prepared_content_type: 'image/jpeg',
      original_base64_chars: 20,
      prepared_base64_chars: 8,
      target_max_dimension_px: 1024,
      target_quality: 0.7,
    })

    await expect(
      preparePhase6ImageUpload(original, {
        maxInlineBase64Chars: 10,
        transform: async () => ({ base64Content: original }),
      }),
    ).rejects.toThrow('did not reduce')
  })

  it('fails loudly on empty image content', async () => {
    await expect(preparePhase6ImageUpload('   ')).rejects.toThrow('image base64 content is required')
  })

  it('resizes and recompresses oversized images with browser canvas support', async () => {
    const drawImage = vi.fn()
    vi.stubGlobal(
      'createImageBitmap',
      vi.fn(async () => ({ width: 3200, height: 1200, close: vi.fn() })),
    )
    const originalCreateElement = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation((tagName: string) => {
      if (tagName !== 'canvas') {
        return originalCreateElement(tagName)
      }
      return {
        width: 0,
        height: 0,
        getContext: vi.fn(() => ({ drawImage })),
        toDataURL: vi.fn(() => 'data:image/jpeg;base64,abc123'),
      } as unknown as HTMLCanvasElement
    })

    const prepared = await preparePhase6ImageUpload('x'.repeat(100), {
      maxInlineBase64Chars: 10,
      targetMaxDimension: 1600,
      targetQuality: 0.8,
    })

    expect(globalThis.createImageBitmap).toHaveBeenCalledWith(expect.any(Blob))
    expect(drawImage).toHaveBeenCalledWith(expect.objectContaining({ width: 3200, height: 1200 }), 0, 0, 1600, 600)
    expect(prepared).toMatchObject({
      base64Content: 'abc123',
      contentType: 'image/jpeg',
      metadata: {
        status: 'compressed',
        original_content_type: 'image/png',
        prepared_content_type: 'image/jpeg',
        prepared_base64_chars: 6,
      },
    })
  })

  it('explains preserve-original consent when browser compression is unavailable', async () => {
    vi.stubGlobal('createImageBitmap', undefined)

    await expect(compressPhase6ImageInBrowser({
      base64Content: 'eA==',
      contentType: 'image/png',
      targetMaxDimension: 1600,
      targetQuality: 0.8,
    })).rejects.toThrow('preserve-original consent')
  })
})
