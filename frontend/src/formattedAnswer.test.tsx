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
    render(<FormattedAnswer text="Do not open [unsafe](javascript:alert(1))." />)

    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(screen.getByText(/javascript:alert/)).toBeInTheDocument()
  })
})
