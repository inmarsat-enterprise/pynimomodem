import os


def dprint(raw_string: str) -> str:
    """Returns a printable string on single line."""
    return raw_string.replace('\r', '<cr>').replace('\n', '<lf>')


def vlog(tag: str = 'NONE') -> bool:
    """Returns True if the tag is in the LOG_VERBOSE environment variable."""
    return tag in str(os.getenv('LOG_VERBOSE'))
