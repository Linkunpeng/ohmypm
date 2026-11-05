import { KeyRound } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/** Shown when the API answers 401: the browser has no access cookie yet. */
export function SignIn() {
  const [token, setToken] = useState("");
  return (
    <div className="flex min-h-svh items-center justify-center p-6">
      <div className="w-full max-w-md space-y-5">
        <div className="flex items-center gap-2">
          <img src="/favicon.svg" alt="" className="size-7" />
          <span className="text-lg font-semibold">ohmypm</span>
        </div>
        <h1 className="text-xl font-semibold">Open the link from your terminal</h1>
        <p className="text-[0.95rem] leading-relaxed text-muted-foreground">
          <code className="font-mono text-foreground">ohmypm web</code> printed a link containing an access token.
          Opening it once signs this browser in. Other users on this machine cannot read your records without it.
        </p>
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            const value = token.trim().replace(/^.*[?&]token=/, "");
            if (value) window.location.assign(`/?token=${encodeURIComponent(value)}`);
          }}
        >
          <Label htmlFor="token">Or paste the token or the whole link</Label>
          <div className="flex gap-2">
            <Input id="token" value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off" />
            <Button type="submit">
              <KeyRound /> Sign in
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            The token is stored in <code className="font-mono">~/.local/share/ohmypm/web-token</code>.
          </p>
        </form>
      </div>
    </div>
  );
}
