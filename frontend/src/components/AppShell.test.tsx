import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import { AppShell } from './AppShell'

vi.mock('@/lib/api', () => ({ api: { decisions: () => Promise.resolve({ total: 0 }) } }))
vi.mock('next-themes', () => ({ useTheme: () => ({ resolvedTheme: 'light', setTheme: vi.fn() }) }))

describe('mobile navigation', () => {
  it('opens the navigation sheet and closes it when a destination is selected', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><MemoryRouter><AppShell onLogout={() => undefined} /></MemoryRouter></QueryClientProvider>)
    fireEvent.click(screen.getByRole('button', { name: 'Open navigation' }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('link', { name: 'Agent Runner' }).at(-1)!)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
