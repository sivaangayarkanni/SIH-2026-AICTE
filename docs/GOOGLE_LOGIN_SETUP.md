# Google sign-in setup (SealCheck on Vercel)

SealCheck uses **Sign in with Google** (OpenID Connect, authorization code + PKCE, confidential client).
The server verifies the Google ID token signature against Google's JWKS, checks `iss`, `aud`, `exp` and `nonce`,
and only accepts accounts whose `email_verified` is true.

Until the two values below are set, the login page shows **"Google sign-in is not configured"** and nobody can sign in.
Nothing in this repository creates a Google Cloud project for you.

## 1. Create the OAuth client (Google Cloud Console, about 10 minutes)

1. Open https://console.cloud.google.com/ and create (or pick) a project, for example `sealcheck-prototype`.
2. **APIs & Services → OAuth consent screen** (called **Google Auth Platform → Branding / Audience** in the newer console):
   - User type: **External** (or **Internal** if every user is in your Google Workspace).
   - App name: `SealCheck (prototype)`. Support email: yours.
   - App domain / homepage: `https://sealcheck-nu.vercel.app`.
   - Scopes: only `openid`, `email` and `profile` (non-sensitive, so no Google verification review is needed).
   - Publishing status **Testing**: add every person who should be able to sign in under **Test users**
     (up to 100). Switch to **In production** later if anyone with a Google account should be able to sign up.
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   - Application type: **Web application**. Name: `SealCheck Vercel`.
   - Authorized JavaScript origins: `https://sealcheck-nu.vercel.app`
   - Authorized redirect URIs (must match exactly):
     `https://sealcheck-nu.vercel.app/api/auth/google/callback`
   - For local testing also add `http://localhost:8000/api/auth/google/callback`.
4. Copy the **Client ID** (ends in `.apps.googleusercontent.com`) and the **Client secret**.

## 2. Give them to Vercel

```bash
vercel env add GOOGLE_CLIENT_ID production        # paste the client ID
vercel env add GOOGLE_CLIENT_SECRET production --sensitive   # paste the secret
vercel env add SEALCHECK_BOOTSTRAP_ADMIN_EMAIL production    # the Google email of the first administrator
vercel deploy --prod
```

`SEALCHECK_BOOTSTRAP_ADMIN_EMAIL` is currently a placeholder (`admin-placeholder@example.invalid`); replace it
with your real Google address (`vercel env rm SEALCHECK_BOOTSTRAP_ADMIN_EMAIL production`, then add it again).
When that person signs in with Google they become administrator; nobody else can give themselves admin or officer rights.

## 3. What users see

1. **Continue with Google** → Google account chooser → back to SealCheck.
2. First sign-in: a profile form asks for full name, role (college representative / AICTE officer request),
   institution name, AICTE institution or application ID, state, designation, mobile number (validated, Indian
   10-digit), the official email (taken from Google, read-only) and a consent checkbox.
3. Access rules:
   - College representative of an institution ID nobody has registered yet: access to that institution immediately.
   - Second representative of an already registered institution: waits for an administrator.
   - AICTE officer: always waits for an administrator (Admin → System health → **Access requests**), who approves as
     officer or senior officer, or declines with a reason.
4. Everything (sign-in, onboarding, approvals) is written to the hash-chained audit log.

## Troubleshooting
| Symptom | Fix |
|---|---|
| `redirect_uri_mismatch` from Google | The redirect URI in step 1.3 must be exactly `https://sealcheck-nu.vercel.app/api/auth/google/callback` (https, no trailing slash). `PUBLIC_BASE_URL` in Vercel must be `https://sealcheck-nu.vercel.app`. |
| "Access blocked: app has not completed verification" | The consent screen is in Testing and this account is not in **Test users**. |
| "Google account email is not verified" | The Google account has an unverified address; verify it in the Google account first. |
| Button greyed out, "not configured" | `GOOGLE_CLIENT_ID` or `GOOGLE_CLIENT_SECRET` is missing in the Vercel production environment; add it and redeploy. |
