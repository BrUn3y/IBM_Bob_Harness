"""Shared configuration for the Remote Bob API clients."""
import os


def api_url() -> str:
    """Resolve the API URL, accepting the legacy name for existing deployments."""
    return (
        os.environ.get("REMOTE_BOB_URL")
        or os.environ.get("HARNESS_URL")
        or "http://localhost:8080"
    )
