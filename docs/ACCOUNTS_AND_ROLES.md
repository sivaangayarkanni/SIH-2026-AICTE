# Accounts and roles (username + password)

Production runs with `AUTH_MODE=password`. Nobody needs a Google or other identity-provider key.
OIDC (`AUTH_MODE=oidc`) and Google (`AUTH_MODE=google`) are still in the code as optional modes. They are **off by default**.

## Roles

| Role (`users.role`) | Signup label | Access after signup |
|---|---|---|
| `college` | College / institution representative | Immediate, if this is the **first** representative of a new AICTE ID. A second signup for an existing institution waits for an administrator. |
| `evc_member` | Expert Visit Committee member | Pending until an administrator approves |
| `officer` | Regional officer (scrutiny) | Pending. A region is required, and approval assigns that region. |
| `senior_officer` | Bureau officer (senior) | Pending. The region is optional (blank means all regions). |
| `admin` | Not selectable at signup | Only from bootstrap/first-run setup, or a role change by another administrator |

A pending user can only see the onboarding status page.
Administrators approve or decline requests under **System health → Access requests**.
Under **User accounts** they can change roles and reset passwords.

## Signup fields
- **Everyone:** full name, username (3–32 characters, `a-z 0-9 . _ -`), email, 10-digit mobile number, password + confirmation, and consent.
- **College:** institution name, AICTE institution/application ID, state/UT and designation.
- **Officer:** region (from the workflow config) and designation.

Validation errors come back per field (`422 {message, fields}`).
A duplicate username or email returns one generic `409`, so an attacker cannot learn which one already exists.
Signups are limited to 10 per hour per IP address.

## Password policy and storage
- 10–128 characters, mixing at least 3 of: lower-case, upper-case, digits, symbols.
- Rejected if it is on the bundled common-password list (`backend/app/rules/common_passwords.txt`), or if it contains the username or the email name.
- Optional breach check: `PASSWORD_BREACH_CHECK=hibp` queries the Have I Been Pwned range API with k-anonymity. Only the first 5 characters of the SHA-1 hash are sent. If the service cannot be reached, the check is skipped (fails open).
- The UI shows a strength meter, and the server re-checks the password through `POST /api/auth/password/check`.
- Hashing is **bcrypt** (cost 12, `SEALCHECK_BCRYPT_ROUNDS`). The password is first SHA-256 hashed, so bcrypt's 72-byte limit never truncates it. Older PBKDF2 hashes still verify and are upgraded to bcrypt at the next sign-in.
- An unknown username still runs a full bcrypt verification, so response timing does not reveal whether an account exists. Hash comparison is constant-time.

## Sign-in, lockout and sessions
- Users sign in with a username **or** an email. Every failure returns the same message.
- There are two limits:
  - Per IP: a rate limit on login attempts per minute.
  - Per account: after 5 consecutive failures the account locks for 1 minute. The lock doubles on each further failure, up to 60 minutes. A successful sign-in or an admin reset clears the counter.
- Sessions use a short-lived bearer JWT, sent in an `Authorization` header and never in a cookie, so there is no CSRF surface.
- Each token carries a `tv` (token version) claim. A **password change**, **Sign out everywhere** (`POST /api/auth/logout-all`), a **role change** or an **admin reset** bumps the version, and every older token is rejected straight away.
- An idle timeout in the UI also signs users out.

## Admin password reset
`POST /api/admin/users/{id}/reset-password` creates a temporary password and shows it **once** to the administrator, who passes it on through an official channel.
The account is unlocked and flagged `must_change`. Until the user picks a new password, every API call apart from the password change returns 403.

## First administrator
Use one of these two options:
1. **Environment bootstrap** (used on the live deployment): set `SEALCHECK_BOOTSTRAP_ADMIN_USERNAME` and `SEALCHECK_BOOTSTRAP_ADMIN_PASSWORD` (optionally also `SEALCHECK_BOOTSTRAP_ADMIN_EMAIL`). The account is created on first start. It is never overwritten after that, so changing the variables later does nothing.
2. **First-run setup page** `/setup`: this works only while there are zero administrators. It runs under a Postgres advisory lock, so two concurrent requests cannot both create one.

## Audit
Each of these writes an audit-log entry: `auth.signup`, `auth.signup_rejected`, `auth.login`, `auth.failed`, `auth.locked_attempt`, `auth.password_changed`, `auth.password_change_failed`, `auth.signout_everywhere`, `auth.password_reset_by_admin`, `access.bootstrap_admin`, `access.first_run_admin`, `access.approved` / decline, and `access.role_changed`.

## Not included (honest gaps)
- **Email verification:** none is sent unless SMTP is configured. The live deployment has no SMTP, so email addresses there are **not verified**.
- **Second factor:** none for password accounts. The OIDC mode supports TOTP through the IdP.
- **Self-service reset:** there is no "forgot password" email. Resets are done by an administrator.
