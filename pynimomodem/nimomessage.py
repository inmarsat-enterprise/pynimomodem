class SatelliteMessage:
    def __init__(self) -> None:
        self.priority = None
        self.state = None
        self.payload = []
        self._message_name = None
    
    def set_name(self, name: str) -> bool:
        pass
    
    def get_name(self) -> str:
        pass
    
    def get_codec_sin(self) -> int:
        pass
    
    def get_codec_min(self) -> int:
        pass
    
    def length(self) -> int:
        pass


class MoMessage(SatelliteMessage):
    """A Mobile-Originated Message."""
    def set_name(self, name: str) -> bool:
        pass


class MtMessage(SatelliteMessage):
    """A Mobile-Terminated message."""


class SatelliteMessageState:
    """State metadata for a message in the NIMO modem's queue."""
    def __init__(self,
                 name: str = '',
                 state: int = 0,
                 length: int = 0,
                 bytes_delivered: int = 0) -> None:
        self.state: int = state
        self.length: int = length
        self.bytes_delivered: int = bytes_delivered
        self._name: str = name
    
    def get_name(self) -> str:
        pass
    
    def set_name(self, name: str) -> bool:
        pass
