import { describe, expect, it } from 'vitest'

import { buildQuery } from './api'
import { duration, timeAgo } from './format'
import { SseParser } from './sse'

describe('SseParser', () => {
  it('parses events split across chunks', () => {
    const p = new SseParser()
    expect(p.feed('retry: 2000\n\nid: 3\nevent: run_ev')).toEqual([])
    const out = p.feed('ent\ndata: {"seq":3}\n\n: keepalive\n\nevent: end\ndata: {"status":"completed"}\n\n')
    expect(out).toEqual([
      { event: 'run_event', data: '{"seq":3}', id: '3' },
      { event: 'end', data: '{"status":"completed"}', id: undefined },
    ])
  })

  it('handles CRLF and multi-line data', () => {
    const p = new SseParser()
    expect(p.feed('data: a\r\ndata: b\r\n\r\n')).toEqual([{ event: 'message', data: 'a\nb', id: undefined }])
  })
})

describe('buildQuery', () => {
  it('skips empty values and repeats arrays', () => {
    expect(buildQuery({ q: '', status: ['todo', 'blocked'], ready: true, limit: 5, x: undefined })).toBe(
      '?status=todo&status=blocked&ready=true&limit=5',
    )
    expect(buildQuery({})).toBe('')
  })
})

describe('format', () => {
  it('formats relative time and durations', () => {
    const now = Date.parse('2026-01-01T00:10:00Z')
    expect(timeAgo('2026-01-01T00:09:30Z', now)).toBe('30s ago')
    expect(timeAgo('2026-01-01T00:00:00Z', now)).toBe('10m ago')
    expect(duration('2026-01-01T00:00:00Z', '2026-01-01T01:05:00Z')).toBe('1h 5m')
    expect(timeAgo(null)).toBe('—')
  })
})
