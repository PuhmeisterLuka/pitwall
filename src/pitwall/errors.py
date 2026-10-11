"""Typed failures for upstream API calls."""


class UpstreamError(Exception):
    """An upstream API call failed."""

    retryable = False

    def __init__(
        self,
        source: str,
        message: str,
        *,
        status: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(f"{source}: {message}")
        self.source = source
        self.message = message  # without the source prefix, for callers that show it
        self.status = status
        self.retry_after = retry_after


class UpstreamNotFound(UpstreamError):
    """The upstream has nothing at this address (404)."""


class UpstreamRateLimited(UpstreamError):
    """The upstream throttled us (429)."""

    retryable = True


class UpstreamUnavailable(UpstreamError):
    """Timeout, connection failure or 5xx."""

    retryable = True


class UpstreamBadResponse(UpstreamError):
    """The upstream sent back something that isn't usable JSON."""
