// OIDC Authorization Code + PKCE (S256) for a public SPA client (Keycloak realm "sealcheck").
// Tokens: access token in localStorage key sealcheck.token (sent as Bearer), refresh/id token in sessionStorage.
export type OidcCfg = { issuer: string; client_id: string; scope: string }
type Disc = { authorization_endpoint: string; token_endpoint: string; end_session_endpoint?: string; issuer: string }

const b64url = (b: ArrayBuffer | Uint8Array) => btoa(String.fromCharCode(...new Uint8Array(b as ArrayBuffer))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
const rand = (n = 32) => b64url(crypto.getRandomValues(new Uint8Array(n)))
const redirectUri = () => `${location.origin}/auth/callback`
let disc: Disc | null = null
let timer: number | undefined

export async function discovery(cfg: OidcCfg): Promise<Disc> {
  if (disc) return disc
  const r = await fetch(`${cfg.issuer}/.well-known/openid-configuration`)
  if (!r.ok) throw new Error('Identity provider unreachable')
  const d = await r.json()
  if (d.issuer.replace(/\/$/, '') !== cfg.issuer.replace(/\/$/, '')) throw new Error('Issuer mismatch')
  return (disc = d)
}

export async function startLogin(cfg: OidcCfg, returnTo = '/') {
  const d = await discovery(cfg)
  const verifier = rand(48), state = rand(16), nonce = rand(16)
  const challenge = b64url(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier)))
  sessionStorage.setItem('sealcheck.pkce', JSON.stringify({ verifier, state, nonce, returnTo }))
  const q = new URLSearchParams({ response_type: 'code', client_id: cfg.client_id, redirect_uri: redirectUri(), scope: cfg.scope,
    code_challenge: challenge, code_challenge_method: 'S256', state, nonce })
  location.assign(`${d.authorization_endpoint}?${q}`)
}

function store(t: any) {
  localStorage.setItem('sealcheck.token', t.access_token)
  if (t.refresh_token) sessionStorage.setItem('sealcheck.refresh', t.refresh_token)
  if (t.id_token) sessionStorage.setItem('sealcheck.id_token', t.id_token)
}

export async function handleCallback(cfg: OidcCfg): Promise<string> {
  const p = new URLSearchParams(location.search)
  const saved = JSON.parse(sessionStorage.getItem('sealcheck.pkce') || 'null')
  sessionStorage.removeItem('sealcheck.pkce')
  if (p.get('error')) throw new Error(p.get('error_description') || p.get('error')!)
  if (!saved || p.get('state') !== saved.state) throw new Error('Sign-in state mismatch — please try again')
  const d = await discovery(cfg)
  const r = await fetch(d.token_endpoint, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ grant_type: 'authorization_code', client_id: cfg.client_id, code: p.get('code') || '', redirect_uri: redirectUri(), code_verifier: saved.verifier }) })
  const t = await r.json()
  if (!r.ok) throw new Error(t.error_description || t.error || 'Token exchange failed')
  const idp = JSON.parse(atob(t.id_token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')))
  if (idp.nonce !== saved.nonce) throw new Error('Nonce mismatch')
  store(t); schedule(cfg, t.expires_in)
  return saved.returnTo || '/'
}

export function schedule(cfg: OidcCfg, expiresIn: number) {
  clearTimeout(timer)
  timer = window.setTimeout(() => refresh(cfg).catch(() => window.dispatchEvent(new Event('sealcheck:logout'))), Math.max(5, expiresIn - 30) * 1000)
}

export async function refresh(cfg: OidcCfg) {
  const rt = sessionStorage.getItem('sealcheck.refresh'); if (!rt) throw new Error('no refresh token')
  const d = await discovery(cfg)
  const r = await fetch(d.token_endpoint, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ grant_type: 'refresh_token', client_id: cfg.client_id, refresh_token: rt }) })
  const t = await r.json(); if (!r.ok) throw new Error(t.error || 'refresh failed')
  store(t); schedule(cfg, t.expires_in)
}

export async function endSession(cfg: OidcCfg) {
  clearTimeout(timer)
  const idt = sessionStorage.getItem('sealcheck.id_token') || ''
  sessionStorage.removeItem('sealcheck.refresh'); sessionStorage.removeItem('sealcheck.id_token')
  const d = await discovery(cfg).catch(() => null)
  if (d?.end_session_endpoint) location.assign(`${d.end_session_endpoint}?${new URLSearchParams({ id_token_hint: idt, post_logout_redirect_uri: `${location.origin}/login`, client_id: cfg.client_id })}`)
}
