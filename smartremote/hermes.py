"""Notification + human-in-the-loop bridge.

Outbound: completion (email), questions (WhatsApp), failures (email).
Inbound: human answers land as files in jobs/<id>/answers/<qid>.txt — written
either by a Hermes inbound webhook or, in fallback mode, by `smartremote answer`.

The default Notifier is `ConsoleNotifier` (prints; writes nothing external) so the
whole system is testable without Hermes. `HermesNotifier` POSTs to a running Hermes
Agent messaging gateway; set base_url/token in config.yaml to enable it.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Protocol


class Notifier(Protocol):
    def send(self, *, channel: str, subject: str, body: str, job_id: str) -> None: ...


class ConsoleNotifier:
    """Fallback notifier: prints to stdout. No external dependency."""

    def send(self, *, channel: str, subject: str, body: str, job_id: str) -> None:
        if channel == "none":
            return
        print(f"[notify:{channel}] job={job_id} :: {subject}\n{body}\n", flush=True)


class HermesNotifier:
    """Thin HTTP client for a Hermes Agent messaging gateway.

    Hermes routes by channel (whatsapp/email/telegram/...). Auth and the exact
    route come from your Hermes deployment; adjust the path/payload to match.
    """

    def __init__(self, base_url: str, token: str | None = None, timeout: float = 10.0,
                 send_path: str = "/send"):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.send_path = "/" + send_path.lstrip("/")

    def send(self, *, channel: str, subject: str, body: str, job_id: str) -> None:
        if channel == "none":
            return
        payload = {"channel": channel, "subject": subject, "body": body, "job_id": job_id}
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(
            f"{self.base_url}{self.send_path}",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
            resp.read()


def build_notifier(cfg: dict) -> Notifier:
    h = (cfg or {}).get("hermes") or {}
    if h.get("enabled") and h.get("base_url"):
        return HermesNotifier(h["base_url"], h.get("token") or None,
                              send_path=h.get("send_path", "/send"))
    return ConsoleNotifier()
