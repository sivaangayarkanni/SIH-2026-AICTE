"""Security/ops event bus. Fan-out to SIEM + notification channels is configured in app.notify (Stage H)."""
import logging
log = logging.getLogger("sealcheck.events")


def notify_event(kind: str, data: dict):
    try:
        from . import notify
        notify.dispatch(kind, data)
    except ImportError:
        log.info("event %s %s", kind, data)
    except Exception:  # never let alerting break the request path
        log.exception("event dispatch failed: %s", kind)
