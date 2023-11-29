"""Class and methods for managing messages submitted/retrieved to a NIMO modem.

This module encapsulates the key concepts of operation for:

* **Mobile-Originated** (aka From-Terminal, Return) messages
* **Mobile-Terminated** (aka To-Terminal, Forward) messages
* Codec key concepts using **SIN** (Service Identification Number) and
**MIN** (Message Identification Number) as the first 2 bytes of message payload.
* Local message metadata such as **state** and **priority**.

"""
import logging

from .constants import (
    MSG_MO_NAME_MAX_LEN,
    MSG_MO_NAME_QMAX_LEN,
    MessagePriority,
    MessageState,
)
from .nimoutils import vlog

VLOG_TAG = 'nimomessage'

_log = logging.getLogger(__name__)


class NimoMessage:
    """A satellite message.
    
    Attributes:
        name (str): The message name in the modem's queue.
        priority (MessagePriority): The priority assigned.
        state (MessageState): The message state.
        payload (bytes): The data content of the message.
        codec_sin (int): The first byte of payload.
        codec_min (int): The second byte of payload.
        length (int): The size of the payload.
    
    """
    def __init__(self,
                 name: str = '',
                 priority: MessagePriority = MessagePriority.NONE,
                 state: MessageState = MessageState.UNAVAILABLE,
                 length: int = 0,
                 bytes_delivered: int = 0,
                 payload: bytes = b'',
                 ) -> None:
        self._message_name: str = ''
        if name:
            self.name = name
        self._priority = MessagePriority.NONE
        if priority is not None:
            self.priority = priority
        self._state = MessageState.UNAVAILABLE
        if state is not None:
            self.state = state
        self._length: int = 0
        if length:
            self.length = length
        self._bytes_delivered: int = 0
        if bytes_delivered:
            self.bytes_delivered = bytes_delivered
        self.payload: bytes = payload
    
    @property
    def name(self) -> str:
        return self._message_name
    
    @name.setter
    def name(self, message_name: str):
        if not isinstance(message_name, str) or len(message_name) == 0:
            raise ValueError('Invalid message name')
        self._message_name = message_name
    
    @property
    def priority(self) -> MessagePriority:
        return self._priority
    
    @priority.setter
    def priority(self, value: MessagePriority):
        if not MessagePriority.is_valid(value):
            raise ValueError('Invalid MessagePriority')
        self._priority = MessagePriority(value)
    
    @property
    def state(self) -> MessageState:
        return self._state
    
    @state.setter
    def state(self, value: MessageState):
        if not MessageState.is_valid(value):
            raise ValueError('Invalid MessagePriority')
        self._state = MessageState(value)
    
    @property
    def codec_sin(self) -> int:
        if self.payload and len(self.payload) > 2:
            return int(self.payload[0])
        return -1
        
    @property
    def codec_min(self) -> int:
        if self.payload and len(self.payload) > 2:
            return int(self.payload[1])
        return -1
    
    @property
    def length(self) -> int:
        if (self._length < len(self.payload) or
            len(self.payload) > 2 and self._length != len(self.payload)):
            # update to actual length
            if vlog(VLOG_TAG):
                _log.debug('Updating message length to align with payload')
            self._length = len(self.payload)
        return self._length
    
    @length.setter
    def length(self, value: int):
        if not isinstance(value, int) or value <= 0:
            raise ValueError('Invalid message length')
        if len(self.payload) > 1 and value != len(self.payload):
            # >1 condition allows for SIN peel-off from MT parsing
            _log.warn('Length mismatch with payload size')
        self._length = value
    
    @property
    def bytes_delivered(self) -> int:
        return self._bytes_delivered
    
    @bytes_delivered.setter
    def bytes_delivered(self, value: int):
        if not isinstance(value, int) or value < 0:
            raise ValueError('Invalid bytes delivered')
        if value > self.length:
            _log.error('Bytes delivered mismatch with message length')
            return
        self._bytes_delivered = value


class MoMessage(NimoMessage):
    """A Mobile-Originated Message."""
    @property
    def name(self) -> str:
        return self._message_name
    
    @name.setter
    def name(self, message_name: str):
        msg_mo_name_max_len = max(MSG_MO_NAME_MAX_LEN, MSG_MO_NAME_QMAX_LEN)
        if (not isinstance(message_name, str) or
            not 0 < len(message_name) <= msg_mo_name_max_len):
            raise ValueError('Invalid message name')
        self._message_name = message_name
    

class MtMessage(NimoMessage):
    """A Mobile-Terminated message."""
    @property
    def bytes_delivered(self) -> int:
        if self._bytes_delivered < self.length:
            # bytes delivered not updated during parsing - update
            self._bytes_delivered = self.length
        return self._bytes_delivered

    @bytes_delivered.setter
    def bytes_delivered(self, value: int):
        if not isinstance(value, int) or value < 0:
            raise ValueError('Invalid bytes delivered')
        if value > self.length:
            _log.error('Bytes delivered mismatch with message length')
            return
        self._bytes_delivered = value
