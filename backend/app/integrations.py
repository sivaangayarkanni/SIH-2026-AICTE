"""Integration hooks (documented interface only; no external system is connected in this prototype).

1. Outbound events: every workflow escalation is emitted as event 'workflow.escalation' through notify.dispatch, so any
   configured channel (webhook / Slack / SIEM / email, see notify.py and NOTIFY_CHANNELS) receives it with retries.
2. Inbound adapters: implement `PortalAdapter` to pull application status from, or push stage changes to, an external
   approval portal. Nothing implements it here; `ADAPTERS` is empty on purpose."""
from __future__ import annotations
from typing import Protocol


class PortalAdapter(Protocol):
    name: str

    def fetch_applications(self, since_iso: str) -> list[dict]:
        """Return [{external_id, institution_code, category, submitted_at, deadline}] changed since a timestamp."""

    def push_stage_change(self, external_id: str, stage: str, action: str, reason: str | None) -> None:
        """Mirror a SealCheck stage change (advanced / returned / reverted / completed) to the external system."""

    def push_alert(self, external_id: str, kind: str, level: str, message: str) -> None:
        """Mirror a reminder / escalation."""


ADAPTERS: dict[str, PortalAdapter] = {}

EVENTS = ["workflow.routed", "workflow.advanced", "workflow.returned", "workflow.resubmitted", "workflow.reverted",
          "evc.scheduled", "evc.completed", "undertaking.created", "undertaking.verified", "validity.renewal_verified",
          "crosscheck.notified", "workflow.escalation"]


def describe() -> dict:
    from . import notify
    return {"adapters": sorted(ADAPTERS), "outbound_channels": notify.channels(),
            "audit_events": EVENTS, "webhook_event": "workflow.escalation",
            "note": "No external portal is connected. See docs/WORKFLOW.md#integration-hooks for the adapter contract."}
