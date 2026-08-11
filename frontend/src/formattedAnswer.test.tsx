import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { FormattedAnswer } from './OpenAgronomyApp'


describe('FormattedAnswer', () => {
  it('renders an official HTTPS reference as a safe external link', () => {
    render(
      <FormattedAnswer text="When connected, check [Nutrient Management](https://example.gov/agriculture/nutrients)." />,
    )

    const link = screen.getByRole('link', { name: 'Nutrient Management' })
    expect(link).toHaveAttribute('href', 'https://example.gov/agriculture/nutrients')
  })

  it('does not turn a non-HTTPS Markdown target into a clickable link', () => {
    const { container } = render(<FormattedAnswer text="Do not open [unsafe](javascript:alert(1))." />)

    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(container).toHaveTextContent('Do not open unsafe.')
  })

  it('preserves spaced numeric ranges instead of inventing list bullets', () => {
    const { container } = render(<FormattedAnswer text="Mapped slope is 0 - 2% across the dominant polygon." />)

    expect(screen.getByText('Mapped slope is 0 - 2% across the dominant polygon.')).toBeInTheDocument()
    expect(container.querySelector('li')).toBeNull()
  })

  it('renders compact model-produced star bullets as separate list rows', () => {
    const { container } = render(
      <FormattedAnswer text="Checks: * **Method:** Confirm Olsen. * **Units:** Confirm ppm." />,
    )

    expect(container.querySelectorAll('li')).toHaveLength(2)
    expect(screen.getByText('Confirm Olsen.')).toBeInTheDocument()
    expect(screen.getByText('Confirm ppm.')).toBeInTheDocument()
  })

  it('renders headings, numbered steps, blockquotes, and code without raw HTML', () => {
    const { container } = render(
      <FormattedAnswer text={'## Next steps\n\n1. Compare zones\n2. Sample roots\n\n> Regional prior only.\n\nUse `EC`.\n\n<script>alert(1)</script>'} />,
    )

    expect(screen.getByRole('heading', { name: 'Next steps' })).toBeInTheDocument()
    expect(container.querySelectorAll('ol li')).toHaveLength(2)
    expect(container.querySelector('blockquote')).toHaveTextContent('Regional prior only.')
    expect(container.querySelector('code')).toHaveTextContent('EC')
    expect(container.querySelector('script')).toBeNull()
    expect(screen.queryByText('alert(1)')).not.toBeInTheDocument()
  })
})
