# Keycloak realm (UNTESTED against a real Keycloak)

`sealcheck-realm.json` is a hand-written realm export for Keycloak 24+: public SPA client `sealcheck-web`
(PKCE S256 only, no implicit/direct grants), realm roles `sealcheck-*`, an audience mapper for `sealcheck-api`,
`college_code` user attribute claim, `amr` mapper, refresh-token rotation, 15-min SSO idle timeout, brute-force
protection, and a browser flow that requires TOTP for staff.

Caveats the operator must check on import:
* `conditional-user-role` takes ONE role; duplicate the `sealcheck-staff-otp` sub-flow for `sealcheck-senior-officer`
  and `sealcheck-admin` (or give staff a composite role) so all staff get the OTP step.
* The API checks MFA via the `amr` claim (`otp`) or `acr` (`2`/`mfa`). Confirm your Keycloak version emits these.
* Replace `sealcheck.example.gov.in` with your hostname. No users are included; create them and set `college_code`.

Import: `kc.sh import --file sealcheck-realm.json` (or mount into `/opt/keycloak/data/import` with `--import-realm`).
Java and Docker are not available on the build box, so this file was validated only as JSON and against the mock IdP's claim shape.
