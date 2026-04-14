"""HTTP client for sending events and heartbeats to the central Sentinel API."""

import logging
from datetime import datetime, timezone

import requests

from agent.collector import CommitMetadata
from agent.queue import EventQueue

logger = logging.getLogger("sentinel.reporter")

_TIMEOUT = 15  # seconds


class Reporter:
    """Sends deploy events and heartbeats to the Sentinel API.

    When the API is unreachable, events are queued locally and
    flushed on the next successful contact.
    """

    def __init__(self, api_url: str, api_token: str, queue_file: str):
        self.api_url = api_url.rstrip("/")
        self.api_token = api_token
        self.queue = EventQueue(queue_file)
        self._headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }

    def send_event(
        self,
        server_id: str,
        environment: str,
        repo_alias: str,
        metadata: CommitMetadata,
    ) -> bool:
        """Post a deploy event to the API. Returns True on success."""
        payload = {
            "server_id": server_id,
            "environment": environment,
            "repo_alias": repo_alias,
            "commit_hash": metadata.commit_hash,
            "commit_message": metadata.commit_message,
            "commit_author": metadata.commit_author,
            "commit_timestamp": metadata.commit_timestamp,
            "previous_commit_hash": metadata.previous_commit_hash,
            "files_changed": metadata.files_changed,
            "commit_count": metadata.commit_count,
            "contributors": metadata.contributors,
            "branch": metadata.branch,
            "detected_at": datetime.now(timezone.utc).isoformat(),
        }

        self._flush_queue()

        success = self._post("/events", payload)
        if not success:
            self.queue.enqueue(payload)
            logger.warning("Event queued for later delivery: %s@%s", repo_alias, metadata.commit_hash[:12])
        return success

    def send_heartbeat(
        self,
        server_id: str,
        environment: str,
        repos: list[str],
        agent_version: str,
    ) -> bool:
        """Post a heartbeat to the API. Returns True on success."""
        payload = {
            "server_id": server_id,
            "environment": environment,
            "repos_watched": repos,
            "agent_version": agent_version,
        }
        return self._post("/heartbeat", payload)

    def _post(self, endpoint: str, payload: dict) -> bool:
        url = f"{self.api_url}{endpoint}"
        try:
            resp = requests.post(url, json=payload, headers=self._headers, timeout=_TIMEOUT)
            if resp.status_code in (200, 201):
                logger.debug("POST %s -> %d", endpoint, resp.status_code)
                return True
            if resp.status_code == 409:
                logger.debug("Duplicate event, API returned 409 for %s", endpoint)
                return True
            logger.error("POST %s -> %d: %s", endpoint, resp.status_code, resp.text[:200])
            return False
        except requests.ConnectionError:
            logger.error("Connection failed: %s", url)
            return False
        except requests.Timeout:
            logger.error("Request timed out: %s", url)
            return False
        except requests.RequestException as e:
            logger.error("Request error for %s: %s", url, e)
            return False

    def _flush_queue(self) -> None:
        """Attempt to send all queued events. Stop on first failure."""
        events = self.queue.peek_all()
        if not events:
            return

        logger.info("Flushing %d queued events", len(events))
        flushed = 0
        for event in events:
            event.pop("project", None)
            event.pop("client", None)
            if self._post("/events", event):
                flushed += 1
            else:
                break

        if flushed > 0:
            self.queue.drop_first(flushed)
            logger.info("Flushed %d/%d queued events", flushed, len(events))
