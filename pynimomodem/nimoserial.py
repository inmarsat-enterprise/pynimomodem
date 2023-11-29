"""Adapter for PySerial methods to Micropython machine.UART methods.

This module attempts to enable compatibility with microcontrollers running
Micropython.

"""
try:
    from serial import Serial
except ImportError:
    from machine import UART
    from .constants import BAUDRATES
    

    class SerialException(Exception):
        """Proxy error for PySerial mapping."""
    
    
    class SerialTimeoutException(SerialException):
        """Proxy error for PySerial mapping."""
    
    
    class Serial(UART):
        """Maps Micropython machine.UART to equivalent serial.Serial methods."""
        def __init__(self,
                    port: 'str|int|None',
                    baudrate: int = 9600,
                    bytesize: int = 8,
                    parity: str ='N',
                    stopbits: int = 1,
                    **kwargs) -> None:
            """"""
            if not isinstance(port, int):
                raise ValueError('Serial proxy must be an integer UART number')
            if baudrate not in BAUDRATES:
                raise ValueError(f'Baudrate must be in {BAUDRATES}')
            if parity == 'N':
                parity = None
            elif parity == 'E':
                parity = 0
            elif parity == 'O':
                parity = 1
            else:
                raise ValueError('Supported parities N, E, O')
            if bytesize not in [8]:
                raise ValueError('Invalid bytesize must be 8')
            if stopbits not in [1]:
                raise ValueError('Invalid stopbits must be 1')
            super().__init__(port, baudrate)
            init_kwargs = {}
            for k, v in kwargs.items():
                if k in ['tx', 'rx', 'timeout', 'timeout_char']:
                    init_kwargs[k] = v
                elif k == 'inter_byte_timeout':
                    init_kwargs['timout_char'] = v
            super().init(baudrate=baudrate, bits=bytesize, parity=parity,
                         stop=stopbits, **init_kwargs)
        
        def open(self) -> None:
            """Open port with current settings.
            
            *Not required* - opened automatically on creation.
            This may throw a SerialException if the port cannot be opened.
            
            """
            pass
        
        def close(self) -> None:
            """Close port.
            
            *Not required* - closed automatically on destruction.
            
            """
            pass
        
        @property
        def in_waiting(self) -> int:
            """Return the number of bytes currently in the input buffer."""
            return super().any()

        def read(self, size: int = 1) -> bytes:
            """Read size bytes from the serial port.
            
            If a timeout is set it may return less characters than requested.
            With no timeout it will block until the requested number of bytes
            is read.
            """
            return super().read(size)
        
        def write(self, data: bytes) -> int:
            """Output the given bytes/buffer over the serial port."""
            written = super().write(data)
            if written is None:
                raise SerialTimeoutException
            return written
