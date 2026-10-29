import { getToken } from './auth'

export interface SseMessage {
  event: string
  data: string
  id?: string
}

/** Incremental parser for the text/event-stream format. */
export class SseParser {
  private buffer = ''
  private event = 'message'
  private data: string[] = []
  private id: string | undefined

  feed(chunk: string): SseMessage[] {
    this.buffer += chunk
    const out: SseMessage[] = []
    let newline: number
    while ((newline = this.buffer.search(/\r?\n/)) >= 0) {
      const line = this.buffer.slice(0, newline)
      this.buffer = this.buffer.slice(newline + (this.buffer[newline] === '\r' ? 2 : 1))
      if (line === '') {
        if (this.data.length) out.push({ event: this.event, data: this.data.join('\n'), id: this.id })
        this.event = 'message'
        this.data = []
        this.id = undefined
        continue
      }
      if (line.startsWith(':')) continue
      const colon = line.indexOf(':')
      const field = colon < 0 ? line : line.slice(0, colon)
      const value = colon < 0 ? '' : line.slice(colon + 1).replace(/^ /, '')
      if (field === 'event') this.event = value
      else if (field === 'data') this.data.push(value)
      else if (field === 'id') this.id = value
    }
    return out
  }
}

export interface StreamOptions {
  lastEventId?: number
  onMessage: (msg: SseMessage) => void
  onError?: (err: unknown) => void
  signal: AbortSignal
}

/**
 * fetch-based SSE (EventSource cannot send Authorization headers). Reconnects with
 * Last-Event-ID until an `end` event arrives or the signal aborts.
 */
export async function streamEvents(url: string, opts: StreamOptions): Promise<void> {
  let last = opts.lastEventId ?? 0
  let delay = 1000
  while (!opts.signal.aborted) {
    try {
      const token = getToken()
      const res = await fetch(url, {
        headers: {
          Accept: 'text/event-stream',
          'Last-Event-ID': String(last),
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        signal: opts.signal,
      })
      if (!res.ok || !res.body) throw new Error(`stream failed: ${res.status}`)
      delay = 1000
      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
      const parser = new SseParser()
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        for (const msg of parser.feed(value)) {
          if (msg.id) last = Number(msg.id)
          opts.onMessage(msg)
          if (msg.event === 'end') return
        }
      }
    } catch (err) {
      if (opts.signal.aborted) return
      opts.onError?.(err)
    }
    await new Promise((resolve) => setTimeout(resolve, delay))
    delay = Math.min(delay * 2, 15000)
  }
}
