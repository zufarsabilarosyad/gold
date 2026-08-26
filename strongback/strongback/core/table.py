"""A fixed-width table renderer, because every report in here is a grid.

Reports are plain text on purpose: a pay application is read in a trailer, in
an email, and in a diff, and a fixed-width table survives all three.  The
renderer is deterministic -- column widths come from the content, ties break
toward the header -- so two runs of the same report are byte-identical.
"""

from ..errors import InputError
from .text import pad, truncate

__all__ = ["Column", "Table", "simple_table", "key_value_block"]


class Column:
    """One column: a header, an alignment, and how to get the cell text."""

    __slots__ = ("key", "header", "align", "width", "formatter")

    def __init__(self, key, header=None, align="left", width=None, formatter=None):
        self.key = str(key)
        self.header = str(header) if header is not None else self.key
        if align not in ("left", "right", "center", "centre"):
            raise InputError("unknown alignment %r" % (align,))
        self.align = align
        self.width = int(width) if width else None
        self.formatter = formatter

    def cell(self, row):
        """Return the rendered text of this column for a row."""
        if isinstance(row, dict):
            value = row.get(self.key, "")
        else:
            value = getattr(row, self.key, "")
        if self.formatter is not None:
            value = self.formatter(value)
        text = "" if value is None else str(value)
        if self.width:
            text = truncate(text, self.width)
        return text

    def __repr__(self):
        return "Column(%r, align=%r)" % (self.key, self.align)


class Table:
    """A list of columns and rows that renders to fixed-width text.

    >>> table = Table([Column("code", "Code"), Column("value", "Value", "right")])
    >>> table.add({"code": "03300", "value": "1,000"})
    >>> table.add({"code": "09900", "value": "250"})
    >>> print(table.render())
    Code   Value
    -----  -----
    03300  1,000
    09900    250
    """

    def __init__(self, columns, rows=(), gap=2, rule="-"):
        self.columns = list(columns)
        if not self.columns:
            raise InputError("a table needs at least one column")
        self.rows = list(rows)
        self.gap = int(gap)
        self.rule = str(rule)[:1] or "-"
        self.separators = set()
        self.notes = []

    def add(self, row):
        """Append a row."""
        self.rows.append(row)

    def extend(self, rows):
        """Append several rows."""
        for row in rows:
            self.add(row)

    def add_separator(self):
        """Draw a rule before the next row, for a subtotal band."""
        self.separators.add(len(self.rows))

    def add_note(self, note):
        """Attach a footnote line printed under the table."""
        self.notes.append(str(note))

    def widths(self):
        """Return the rendered width of each column."""
        widths = []
        for column in self.columns:
            width = len(column.header)
            for row in self.rows:
                width = max(width, len(column.cell(row)))
            widths.append(width)
        return widths

    def render(self, header=True):
        """Return the table as text with no trailing whitespace on any line."""
        widths = self.widths()
        gap = " " * self.gap
        lines = []
        if header:
            lines.append(
                gap.join(
                    pad(column.header, width, column.align)
                    for column, width in zip(self.columns, widths)
                ).rstrip()
            )
            lines.append(gap.join(self.rule * width for width in widths).rstrip())
        for index, row in enumerate(self.rows):
            if index in self.separators:
                lines.append(gap.join(self.rule * width for width in widths).rstrip())
            lines.append(
                gap.join(
                    pad(column.cell(row), width, column.align)
                    for column, width in zip(self.columns, widths)
                ).rstrip()
            )
        for note in self.notes:
            lines.append(note.rstrip())
        return "\n".join(lines)

    def __len__(self):
        return len(self.rows)

    def __repr__(self):
        return "Table(%d columns, %d rows)" % (len(self.columns), len(self.rows))


def simple_table(headers, rows, aligns=None):
    """Render a table from headers and row tuples in one call.

    >>> print(simple_table(["a", "b"], [(1, 2), (3, 4)]))
    a  b
    -  -
    1  2
    3  4
    """
    aligns = list(aligns or ["left"] * len(headers))
    columns = [
        Column(str(index), header, aligns[index])
        for index, header in enumerate(headers)
    ]
    table = Table(columns)
    for row in rows:
        table.add({str(index): value for index, value in enumerate(row)})
    return table.render()


def key_value_block(pairs, separator=": ", width=None):
    """Render aligned ``key: value`` lines.

    >>> print(key_value_block([("Contract", "C-1"), ("Retainage", "10%")]))
    Contract   : C-1
    Retainage  : 10%
    """
    pairs = [(str(key), "" if value is None else str(value)) for key, value in pairs]
    if not pairs:
        return ""
    width = width or max(len(key) for key, _ in pairs) + 2
    return "\n".join(
        (pad(key, width) + separator + value).rstrip() for key, value in pairs
    )
