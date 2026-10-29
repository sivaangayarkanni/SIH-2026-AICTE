# Workflow: routes, deadlines, escalation, calendar, EVC, compliance and reports

> **Safeguard:** Automated alerts, recommendations and workflow actions support the approval process. They do not replace statutory scrutiny, verification, inspections or decisions taken by the competent authority.

Everything below is driven by `backend/app/rules/workflow.yaml`. It is versioned, and every saved version is signed (HMAC with a key derived from the master key) and stored in `wf_config_versions`. Administrators edit it under **Workflow config**.
Stage names, SLA days, reminder offsets and region names are **editable placeholders**. They are not AICTE Approval Process Handbook clauses, and none are quoted.

## A. Routes and stage movement
- `stages` define the label, SLA days and allowed actors. `routes` list the stages in order, and `route_rules` (first match wins) pick a route from the application category.
- When a stage's conditions are met (for example, the EVC visit is complete), the application advances automatically. Officers can also **advance**, **return to institution** or **revert to a previous stage**. Return and revert need a reason.
- Every move is recorded in `wf_stage_events` and in the audit log.
- API: `POST /api/wf/apps/{id}/advance|return|revert|resubmit`.

## B. Pendency dashboard (`/pendency`)
- Counts by region, stage, officer and institution.
- Ageing buckets (0–7, 8–15, 16–30, more than 30 days).
- Overdue and approaching items, bottleneck stages (the mean time spent in each stage, from stage history), and open alerts.
- API: `GET /api/wf/dashboard`, `GET /api/wf/alerts`.

## C. EVC (`/evc`)
- An application entering an EVC stage creates a queued visit. The visit must be scheduled within `evc.schedule_within_days` and completed within `complete_within_days` (a shorter limit applies to new institutions).
- Officers schedule the date and members. EVC members record observations against the checklist, and an officer closes the visit.
- The **summarised EVC form** is a one-page summary followed by the detail. It is shown on screen and as a PDF (`/api/wf/apps/{id}/evc-summary.pdf`).

## D. Undertakings (`/compliance`)
Undertakings have due dates. The institution submits evidence, and an officer verifies or rejects it. A missed due date escalates.

## E. Document validity
The validity end date is tracked for the types listed in `validity_doc_types` (land, fire NOC, bank FDR and others). Reminders go out before expiry. The institution uploads a renewal, and an officer verifies it.

## Deadline reminders and escalation
`reminders` lists the days **before** a due date when a reminder is sent. `escalation` lists the days **after** it when someone is alerted:

| Item | Reminders before | Escalation after |
|---|---|---|
| Submission deadline | 30, 15, 7, 1 | 0 → Regional officer, 7 → Bureau officer |
| Stage SLA | 3, 1 | 0 → officer, 5 → Bureau officer, 15 → admin |
| EVC visit | 7, 3, 1 | 0 → officer, 7 → Bureau officer |
| Undertaking | 30, 15, 7, 1 | 0 → officer, 7 → Bureau officer |
| Document validity | 60, 30, 15, 7, 1 | 0 → officer, 15 → Bureau officer |

- The evaluator (`workflow.evaluate`) is idempotent: each alert has a unique key, so re-running it never sends duplicates.
- **Production:** Vercel Cron calls `GET /api/cron/evaluate` daily at 02:30 UTC (08:00 IST), with `Authorization: Bearer $CRON_SECRET`. The endpoint is disabled if no secret is set.
- **Development:** set `WF_SCHEDULER_S=300` to run the evaluator in the background, or click **Run deadline check** on the config page.
- Alerts are sent in-app. Email is sent only when SMTP is configured.

## Calendar (`/calendar`)
- Month and agenda views of deadlines, SLA due dates, EVC visits, undertakings and validity expiries, colour-coded by kind.
- A per-user ICS feed (`/api/wf/calendar.ics?uid=…&key=…`, with an HMAC key for each user) can be subscribed to from Google or Outlook calendar.

## Application wizard (`/apply`)
- A Google-Form-like flow: category → institution details → one step per required document → review.
- It has a progress bar, per-step validation, and server-saved drafts (`PUT /api/wf/apps/{id}/draft`), so the institution can stop and resume later.
- **Cross-document check:** core fields (institution name, AICTE ID, address, trust/society, land area, …) are compared across the extracted documents with fuzzy matching (`crosscheck.fuzzy_threshold`). Each mismatch is sent back to the institution as "to be corrected / re-uploaded" and flagged to officers.

## F. Notifications, reports and audit
- **Reports** (`/reports`): pendency, overdue, EVC, undertakings, validity and stage history. Each can be exported as CSV or PDF.
- Every workflow action is written to the hash-chained audit log.

## Integration hooks
`backend/app/integrations.py` defines the `PortalAdapter` interface (`fetch_applications`, `push_stage_change`, `push_alert`). Only a no-op/log adapter ships with the prototype. **No connection to any real AICTE system exists or is claimed.**
