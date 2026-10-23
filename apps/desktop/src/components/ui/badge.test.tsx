import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Badge } from './badge'

describe('Badge', () => {
  it('can render as its child element', () => {
    render(
      <Badge asChild>
        <a href="#/settings">Settings</a>
      </Badge>,
    )

    expect(screen.getByRole('link', { name: 'Settings' })).toHaveAttribute('data-slot', 'badge')
  })
})
