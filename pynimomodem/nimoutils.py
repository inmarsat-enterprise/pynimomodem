"""Various utilities/helpers for NIMO modem interaction and debugging.
"""
import os
from datetime import datetime, timezone
from typing import Iterable


def dprint(raw_string: str) -> str:
    """Returns a printable string on single line."""
    return raw_string.replace('\r', '<cr>').replace('\n', '<lf>')


def vlog(tag: str = 'NONE') -> bool:
    """Returns True if the tag is in the LOG_VERBOSE environment variable."""
    return tag in str(os.getenv('LOG_VERBOSE'))


def ts_to_iso(timestamp: 'float|int', ms: bool = False) -> str:
    """Converts a unix timestamp to ISO 8601 format (UTC).
    
    Args:
        timestamp: A unix timestamp.
        ms: Flag indicating whether to include milliseconds in response
    
    Returns:
        ISO 8601 UTC format e.g. `YYYY-MM-DDThh:mm:ss[.sss]Z`

    """
    iso_time = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
    if not ms:
        return f'{iso_time[:19]}Z'
    return f'{iso_time[:23]}Z'


def iso_to_ts(iso_time: str, ms: bool = False) -> int:
    """Converts a ISO 8601 timestamp (UTC) to unix timestamp.
    
    Args:
        iso_time: An ISO 8601 UTC datetime `YYYY-MM-DDThh:mm:ss[.sss]Z`
        ms: Flag indicating whether to include milliseconds in response
    
    Returns:
        Unix UTC timestamp as an integer, or float if `ms` flag is set.

    """
    if '.' not in iso_time:
        iso_time = iso_time.replace('Z', '.000Z')
    utc_dt = datetime.strptime(iso_time, '%Y-%m-%dT%H:%M:%S.%fZ')
    ts = (utc_dt - datetime(1970, 1, 1)).total_seconds()
    if not ms:
        ts = int(ts)
    return ts


def bits_in_bitmask(bitmask: int) -> Iterable[int]:
    """Get iterable integer value of each bit in a bitmask."""
    while bitmask:
        bit = bitmask & (~bitmask+1)
        yield bit
        bitmask ^= bit
