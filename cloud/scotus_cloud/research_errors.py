"""Expected provider/setup waits do not belong in code recovery."""

class ResearchUnavailable(RuntimeError):
    def __init__(self, kind, message, retry_after=900, phase=''):
        super().__init__(message)
        self.kind = kind
        self.retry_after = max(60, min(86400, int(retry_after)))
        self.phase = phase

