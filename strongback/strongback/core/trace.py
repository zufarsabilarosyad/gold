"""The explain trace: every decision a run made, in the order it made it.

The trace is not logging.  Logging is for the operator; the trace is part of
the answer, and ``strongback explain`` reads it back to show why a line was
billed at the figure it was billed at.  It therefore has to be deterministic,
serialisable, and free of anything that varies between runs -- no timestamps,
no object addresses, no dictionary ordering that depends on hashing.
"""

from ..errors import InputError

__all__ = ["TraceEvent", "Trace", "NULL_TRACE"]


class TraceEvent:
    """One recorded decision.

    ``stage`` names the pipeline step, ``subject`` names what was decided about
    (usually a schedule-of-values code), and ``values`` carries the numbers
    that made the decision, already rendered as strings.

    >>> event = TraceEvent("retainage", "03300", "held at 10%", {"base": "1000.00"})
    >>> event.render()
    'retainage 03300: held at 10% (base=1000.00)'
    """

    __slots__ = ("stage", "subject", "message", "values", "sequence")

    def __init__(self, stage, subject, message, values=None, sequence=0):
        self.stage = str(stage)
        self.subject = str(subject)
        self.message = str(message)
        self.values = {str(key): str(value) for key, value in dict(values or {}).items()}
        self.sequence = int(sequence)

    def render(self, with_values=True):
        """Return the event as one line of text."""
        head = "%s %s: %s" % (self.stage, self.subject, self.message)
        if not with_values or not self.values:
            return head
        detail = ", ".join(
            "%s=%s" % (key, self.values[key]) for key in sorted(self.values)
        )
        return "%s (%s)" % (head, detail)

    def to_dict(self):
        """Return the event as plain data."""
        return {
            "sequence": self.sequence,
            "stage": self.stage,
            "subject": self.subject,
            "message": self.message,
            "values": dict(self.values),
        }

    @classmethod
    def from_dict(cls, data):
        """Rebuild an event from :meth:`to_dict` output."""
        return cls(
            data["stage"],
            data["subject"],
            data["message"],
            data.get("values"),
            data.get("sequence", 0),
        )

    def __eq__(self, other):
        return (
            isinstance(other, TraceEvent)
            and other.stage == self.stage
            and other.subject == self.subject
            and other.message == self.message
            and other.values == self.values
        )

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(("TraceEvent", self.stage, self.subject, self.message))

    def __str__(self):
        return self.render()

    def __repr__(self):
        return "TraceEvent(%r, %r)" % (self.stage, self.subject)


class Trace:
    """An append-only, ordered list of :class:`TraceEvent`.

    >>> trace = Trace()
    >>> trace.record("progress", "03300", "35% complete")
    >>> trace.record("retainage", "03300", "held at 10%")
    >>> len(trace)
    2
    >>> [event.stage for event in trace.for_subject("03300")]
    ['progress', 'retainage']
    """

    __slots__ = ("events", "enabled")

    def __init__(self, enabled=True):
        self.events = []
        self.enabled = bool(enabled)

    def record(self, stage, subject, message, values=None):
        """Append an event, unless this trace is disabled."""
        if not self.enabled:
            return
        self.events.append(
            TraceEvent(stage, subject, message, values, sequence=len(self.events) + 1)
        )

    def extend(self, other):
        """Append every event of another trace, renumbering as it goes."""
        if not self.enabled:
            return
        for event in other:
            self.record(event.stage, event.subject, event.message, event.values)

    def for_subject(self, subject):
        """Return the events about one subject, in order."""
        subject = str(subject)
        return [event for event in self.events if event.subject == subject]

    def for_stage(self, stage):
        """Return the events from one pipeline stage, in order."""
        stage = str(stage)
        return [event for event in self.events if event.stage == stage]

    def subjects(self):
        """Return the distinct subjects in first-seen order."""
        seen = []
        for event in self.events:
            if event.subject not in seen:
                seen.append(event.subject)
        return seen

    def stages(self):
        """Return the distinct stages in first-seen order."""
        seen = []
        for event in self.events:
            if event.stage not in seen:
                seen.append(event.stage)
        return seen

    def render(self, subject=None, stage=None, with_values=True):
        """Return the trace as text, optionally narrowed."""
        events = self.events
        if subject is not None:
            events = [event for event in events if event.subject == str(subject)]
        if stage is not None:
            events = [event for event in events if event.stage == str(stage)]
        return "\n".join(event.render(with_values) for event in events)

    def to_list(self):
        """Return the trace as plain data."""
        return [event.to_dict() for event in self.events]

    @classmethod
    def from_list(cls, data):
        """Rebuild a trace from :meth:`to_list` output."""
        trace = cls()
        for entry in data:
            event = TraceEvent.from_dict(entry)
            trace.record(event.stage, event.subject, event.message, event.values)
        return trace

    def __len__(self):
        return len(self.events)

    def __iter__(self):
        return iter(self.events)

    def __getitem__(self, index):
        return self.events[index]

    def __bool__(self):
        return bool(self.events)

    def __repr__(self):
        return "Trace(%d events)" % (len(self.events),)


class _NullTrace(Trace):
    """A trace that records nothing, for hot paths that do not need one."""

    def __init__(self):
        Trace.__init__(self, enabled=False)

    def record(self, stage, subject, message, values=None):
        """Discard the event."""
        return


NULL_TRACE = _NullTrace()


def require_trace(trace):
    """Return the trace, or a fresh one when ``None`` was passed."""
    if trace is None:
        return Trace()
    if not isinstance(trace, Trace):
        raise InputError("expected a Trace, got %s" % (type(trace).__name__,))
    return trace
