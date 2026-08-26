"""The package version, kept in one place so tooling and reports agree."""

__all__ = ["VERSION", "version_string"]

VERSION = (0, 9, 0)


def version_string():
    """Return the version as a dotted string.

    >>> version_string()
    '0.9.0'
    """
    return ".".join(str(part) for part in VERSION)
