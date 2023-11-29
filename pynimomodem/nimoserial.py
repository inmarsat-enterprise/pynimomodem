"""Adapter for PySerial methods to Micropython machine.UART methods.

This module attempts to enable compatibility with microcontrollers running
Micropython.

"""
try:
    from serial import Serial
except ImportError:
    from machine import UART
    from .constants import BAUDRATES
    import logging
    
    _log = logging.getLogger(__name__)


    class SerialException(Exception):
        """Proxy error for PySerial mapping."""
    
    
    class SerialTimeoutException(SerialException):
        """Proxy error for PySerial mapping."""
    
    
    class Serial(UART):
        """Maps Micropython machine.UART to equivalent serial.Serial methods."""
        def __init__(self, **kwargs) -> None:
            """Initialize the serial port object.
            
            If `port` kwarg is specified the port will be opened immediately,
            otherwise a Serial object in closed state is returned.
            
            Additional kwargs as per
            https://docs.micropython.org/en/latest/library/machine.UART.html
            
            Keyword Args:
                port (int|str): The UART port number
                baudrate (int): The baudrate (default 9600)
                bytesize (int): The number of bits for a char (default 8)
                parity (str|int): `N`one (default), `E`ven (0) or `O`dd (1)
                stopbits (int): The number of stop bits for a char (default 1)
            
            """
            self._port: 'int|None' = None
            self._init_kwargs = {}
            for k, v in kwargs.items():
                if k == 'port':
                    self.port = v
                if k == 'baudrate':
                    if v not in BAUDRATES:
                        raise ValueError(f'baudrate must be in {BAUDRATES}')
                    self._init_kwargs[k] = v
                elif k == 'parity':
                    if v == 'N':
                        self._init_kwargs[k] = None
                    elif v == 'E':
                        self._init_kwargs[k] = 0
                    elif v == 'O':
                        self._init_kwargs[k] = 1
                    else:
                        raise ValueError('Unsupported parity must be N, E or O')
                elif k == 'bytesize':
                    self._init_kwargs['bits'] = v
                elif k == 'stopbits':
                    self._init_kwargs['stop'] = v
                elif k == 'inter_byte_timeout':
                    self._init_kwargs['timeout_char'] = v
                elif k in ['tx', 'rx', 'timeout']:
                    self._init_kwargs[k] = v
            self.is_open: bool = False
            if self._port is not None:
                self.open()
        
        def __del__(self):
            super().deinit()
        
        def _not_closed(self, func):
            if not self.is_open:
                raise SerialException('Serial port is closed')
            return func
        
        def open(self) -> None:
            """Open port with current settings.
            
            *Not required* - opened automatically on creation.
            This may throw a SerialException if the port cannot be opened.
            
            """
            if self.is_open:
                _log.warning('Serial port already open')
                return
            super().init(**self._init_kwargs)
            self.is_open = True
        
        @_not_closed
        def close(self) -> None:
            """Close port.
            
            *Not required* - closed automatically on destruction.
            
            """
            self.is_open = False
        
        @property
        def port(self) -> 'str|int|None':
            if self._port is None:
                return None
            return self._port
        
        @port.setter
        def port(self, value: 'str|int'):
            try:
                self._port = int(value)
                super().__init__(self._port)
            except ValueError as exc:
                raise ValueError('Invalid port') from exc
        
        @property
        def baudrate(self) -> int:
            return self._init_kwargs.get('baudrate', 0)

        @baudrate.setter
        def baudrate(self, value: int):
            if value not in BAUDRATES:
                raise ValueError(f'Invalid baudrate must be in {BAUDRATES}')
            self._init_kwargs['baudrate'] = value
            super().init(**self._init_kwargs)
        
        @_not_closed
        @property
        def in_waiting(self) -> int:
            """Return the number of bytes currently in the input buffer."""
            return super().any()

        @_not_closed
        def read(self, size: int = 1) -> bytes:
            """Read size bytes from the serial port.
            
            If a timeout is set it may return less characters than requested.
            With no timeout it will block until the requested number of bytes
            is read.
            """
            return super().read(size)
        
        @_not_closed
        def write(self, data: bytes) -> int:
            """Output the given bytes/buffer over the serial port."""
            if not self.is_open:
                raise SerialException('Serial port is not open')
            written = super().write(data)
            if written is None:
                raise SerialTimeoutException
            return written
        
        @_not_closed
        def send_break(self, **kwargs) -> None:
            """Send `break` condition.
            
            Drives the bus low for a duration longer than a normal character.
            Supports passing kwargs e.g. `duration` but ignores.
            
            """
            super().sendbreak()
