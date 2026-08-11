export const PHASE6_IMAGE_INLINE_BASE64_BUDGET = 350000
export const PHASE6_IMAGE_TARGET_MAX_DIMENSION = 1600
export const PHASE6_IMAGE_TARGET_QUALITY = 0.82

export type Phase6ImagePreparationMetadata = {
  schema_version: 'phase6.image_upload_preparation.v1'
  preserve_original: boolean
  original_content_type: string
  prepared_content_type: string
  original_base64_chars: number
  prepared_base64_chars: number
  target_max_dimension_px: number
  target_quality: number
  status: 'preserved_original' | 'within_inline_budget' | 'compressed'
}

export type Phase6PreparedImageUpload = {
  base64Content: string
  contentType: string
  metadata: Phase6ImagePreparationMetadata
}

export type Phase6ImageTransform = (input: {
  base64Content: string
  contentType: string
  targetMaxDimension: number
  targetQuality: number
}) => Promise<{ base64Content: string; contentType?: string }>

type PrepareImageOptions = {
  preserveOriginal?: boolean
  maxInlineBase64Chars?: number
  targetMaxDimension?: number
  targetQuality?: number
  transform?: Phase6ImageTransform
}

const normalizeBase64 = (value: string): string => {
  const trimmed = value.trim()
  const comma = trimmed.indexOf(',')
  return trimmed.startsWith('data:') && comma >= 0 ? trimmed.slice(comma + 1).trim() : trimmed
}

const inferContentType = (value: string): string => {
  const match = value.trim().match(/^data:([^;,]+)[;,]/i)
  return match?.[1]?.toLowerCase() || 'image/png'
}

const metadata = (
  status: Phase6ImagePreparationMetadata['status'],
  preserveOriginal: boolean,
  originalContentType: string,
  preparedContentType: string,
  originalChars: number,
  preparedChars: number,
  targetMaxDimension: number,
  targetQuality: number,
): Phase6ImagePreparationMetadata => ({
  schema_version: 'phase6.image_upload_preparation.v1',
  preserve_original: preserveOriginal,
  original_content_type: originalContentType,
  prepared_content_type: preparedContentType,
  original_base64_chars: originalChars,
  prepared_base64_chars: preparedChars,
  target_max_dimension_px: targetMaxDimension,
  target_quality: targetQuality,
  status,
})

export const compressPhase6ImageInBrowser: Phase6ImageTransform = async ({
  base64Content,
  contentType,
  targetMaxDimension,
  targetQuality,
}) => {
  if (typeof document === 'undefined' || typeof createImageBitmap !== 'function' || typeof Blob === 'undefined' || typeof atob !== 'function') {
    throw new Error('image exceeds inline upload budget and needs browser image compression support or preserve-original consent')
  }
  let image: ImageBitmap | undefined
  try {
    const binary = atob(base64Content)
    const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0))
    image = await createImageBitmap(new Blob([bytes], { type: contentType }))
    if (!image.width || !image.height) {
      throw new Error('image compression could not determine image dimensions')
    }

    const scale = Math.min(1, targetMaxDimension / Math.max(image.width, image.height))
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(image.width * scale))
    canvas.height = Math.max(1, Math.round(image.height * scale))
    const context = canvas.getContext('2d')
    if (!context) {
      throw new Error('image exceeds inline upload budget and needs browser image compression support or preserve-original consent')
    }
    context.drawImage(image, 0, 0, canvas.width, canvas.height)
    const preparedContentType = 'image/jpeg'
    return {
      base64Content: canvas.toDataURL(preparedContentType, targetQuality),
      contentType: preparedContentType,
    }
  } finally {
    image?.close()
  }
}

export async function preparePhase6ImageUpload(
  base64Content: string,
  options: PrepareImageOptions = {},
): Promise<Phase6PreparedImageUpload> {
  const normalized = normalizeBase64(base64Content)
  if (!normalized) {
    throw new Error('image base64 content is required')
  }

  const preserveOriginal = Boolean(options.preserveOriginal)
  const maxInlineBase64Chars = options.maxInlineBase64Chars ?? PHASE6_IMAGE_INLINE_BASE64_BUDGET
  const targetMaxDimension = options.targetMaxDimension ?? PHASE6_IMAGE_TARGET_MAX_DIMENSION
  const targetQuality = options.targetQuality ?? PHASE6_IMAGE_TARGET_QUALITY
  const originalContentType = inferContentType(base64Content)

  if (preserveOriginal) {
    return {
      base64Content: normalized,
      contentType: originalContentType,
      metadata: metadata('preserved_original', true, originalContentType, originalContentType, normalized.length, normalized.length, targetMaxDimension, targetQuality),
    }
  }

  if (normalized.length <= maxInlineBase64Chars) {
    return {
      base64Content: normalized,
      contentType: originalContentType,
      metadata: metadata('within_inline_budget', false, originalContentType, originalContentType, normalized.length, normalized.length, targetMaxDimension, targetQuality),
    }
  }

  const transformed = await (options.transform ?? compressPhase6ImageInBrowser)({
    base64Content: normalized,
    contentType: originalContentType,
    targetMaxDimension,
    targetQuality,
  })
  const prepared = normalizeBase64(transformed.base64Content)
  const preparedContentType = transformed.contentType || inferContentType(transformed.base64Content)
  if (!prepared) {
    throw new Error('image compression returned empty content')
  }
  if (prepared.length >= normalized.length) {
    throw new Error('image compression did not reduce upload size')
  }

  return {
    base64Content: prepared,
    contentType: preparedContentType,
    metadata: metadata('compressed', false, originalContentType, preparedContentType, normalized.length, prepared.length, targetMaxDimension, targetQuality),
  }
}
