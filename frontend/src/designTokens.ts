export const phase6DesignTokens = {
  typography: {
    family: 'Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif',
    sizeBody: '14px',
    sizeHeading: '26px',
    sizeSubheading: '17px',
    lineHeightTight: '1.2',
  },
  color: {
    text: '#1f2a24',
    surface: '#ffffff',
    page: '#f6f7f3',
    border: '#d9ded4',
    control: '#eef3ea',
    success: '#2f6f4e',
    caution: '#9a5b19',
    regulated: '#8a3324',
    missingData: '#6b5b95',
    evidence: '#2e5e75',
    source: '#436b38',
    internalDebug: '#4d5663',
  },
} as const

export const requiredPhase6SemanticColorTokens = [
  'success',
  'caution',
  'regulated',
  'missingData',
  'evidence',
  'source',
  'internalDebug',
] as const

export type Phase6SemanticColorToken = (typeof requiredPhase6SemanticColorTokens)[number]
