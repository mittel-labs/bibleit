class OperatorError(Exception):
    """An operator request that can be reported safely to a client."""


class CommandValidationError(OperatorError):
    """A command name or payload does not match the public command contract."""


class CapabilityError(OperatorError):
    """The host did not grant the requested optional capability."""


class PublishError(OperatorError):
    """A publish target rejected a state transition."""

    def __init__(self, message: str, *, committed_sequence: int | None = None):
        super().__init__(message)
        self.committed_sequence = committed_sequence
