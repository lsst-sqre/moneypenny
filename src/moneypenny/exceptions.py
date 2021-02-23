"""Helper exceptions for Moneypenny.
"""


class CatGotYourTongueError(Exception):
    """Used when Moneypenny has no quips."""

    pass


class NonsensicalOrderError(Exception):
    """Used when there is no correspondence to the verb supplied."""

    pass


class NoMrBondIExpectYouToDie(Exception):
    """Used when execution of an order times out."""

    pass


class OperationFailed(Exception):
    """Used when the Pod did not complete execution correctly."""

    pass


class PodNotFound(Exception):
    """Used when the named pod cannot be located."""

    pass


class K8sApiException(Exception):
    """Used to wrap K8s ApiExceptions."""

    pass
