class WampError(Exception): pass
class WampAbort(WampError):
    def __init__(self, reason, details=None):
        super().__init__(reason); self.reason=reason; self.details=details or {}
class WampProtocolError(WampError): pass
class WampTimeout(WampError): pass
