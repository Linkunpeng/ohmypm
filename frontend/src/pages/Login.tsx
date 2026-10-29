import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api, errorMessage } from '@/lib/api'
import { clearToken, setToken } from '@/lib/auth'

export function Login({ onLogin }: { onLogin: () => void }) {
  const [token, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit() {
    setBusy(true)
    setError(null)
    setToken(token.trim())
    try {
      await api.whoami()
      onLogin()
    } catch (err) {
      clearToken()
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>ohmypm</CardTitle>
          <CardDescription>
            Enter the API token (<code>OHMYPM_API_TOKEN</code> from your <code>.env</code>), or open the link printed by{' '}
            <code>ohmypm open</code>.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="grid gap-3"
            onSubmit={(e) => {
              e.preventDefault()
              void submit()
            }}
          >
            <Label htmlFor="token">API token</Label>
            <Input id="token" type="password" autoFocus value={token} onChange={(e) => setValue(e.target.value)} />
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" disabled={!token.trim() || busy}>
              Sign in
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
