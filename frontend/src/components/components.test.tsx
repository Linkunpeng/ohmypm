import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { StatusBadge } from './common'
import { RunEventRow } from './RunLog'

describe('StatusBadge', () => {
  it('renders a readable label and a live dot for running', () => {
    const { container } = render(<StatusBadge status="awaiting_user" />)
    expect(screen.getByText('awaiting user')).toBeInTheDocument()
    render(<StatusBadge status="running" />)
    expect(container.ownerDocument.querySelector('.animate-pulse')).not.toBeNull()
  })
})

describe('RunEventRow', () => {
  it('summarises tool events and expands raw payload', () => {
    render(
      <RunEventRow
        event={{
          id: 1,
          run_id: 'r',
          seq: 7,
          event_type: 'tool.completed',
          timestamp: '2026-01-01T00:00:00Z',
          payload: { tool: 'shell', output: '3 passed', is_error: false },
        }}
      />,
    )
    expect(screen.getByText(/shell ✓ 3 passed/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByText(/"output": "3 passed"/)).toBeInTheDocument()
  })
})
