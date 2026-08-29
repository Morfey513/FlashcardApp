"""Storage-layer failures that must not be confused with missing data."""


class RepositoryUnavailable(RuntimeError):
    """The persistence service could not answer authoritatively."""
