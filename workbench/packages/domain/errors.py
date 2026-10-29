"""Domain errors without configuration, database or provider initialization."""


class DomainError(Exception):
    def __init__(self, code, message, status=409, details=None, retryable=False):
        self.code, self.message, self.status = code, message, status
        self.details, self.retryable = details or {}, retryable
