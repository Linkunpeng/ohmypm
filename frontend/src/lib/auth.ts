const KEY = 'ohmypm.token'

/** Accept a one-time `#token=...` fragment (from `ohmypm open`) and strip it from the URL. */
export function captureTokenFromHash(): void {
  const match = /(?:^|[#&])token=([^&]+)/.exec(window.location.hash)
  if (match?.[1]) {
    setToken(decodeURIComponent(match[1]))
    history.replaceState(null, '', window.location.pathname + window.location.search)
  }
}

export function getToken(): string | null {
  return localStorage.getItem(KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(KEY)
}
