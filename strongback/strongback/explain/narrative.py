"""Turning a trace into sentences.

A trace is a list of decisions in the order they were made, which is the right
shape for a machine and the wrong shape for a person: it interleaves lines.
The narrative regroups it by subject, keeps the order within each subject, and
drops the stages nobody asked about.

Nothing here recomputes anything.  If the narrative and the numbers disagree,
the narrative is the bug.
"""

from ..core.text import indent, wrap
from ..errors import DataError

__all__ = ["narrate", "narrate_subject", "stage_summary"]

_STAGE_TITLES = {
    "progress": "Work in place",
    "stored": "Stored materials",
    "retainage-base": "Retainage base",
    "retainage-stepdown": "Retainage rate",
    "retainage-cap": "Retainage ceiling",
    "retainage-release": "Retainage release",
    "back-charge": "Back-charges",
    "tax": "Tax",
    "allowance": "Allowances",
    "allocation": "Payment allocation",
    "interest": "Interest",
    "joint-check": "Joint cheques",
}


def stage_title(stage):
    """Return a readable title for a trace stage.

    >>> stage_title("retainage-stepdown")
    'Retainage rate'
    >>> stage_title("something-else")
    'Something else'
    """
    stage = str(stage)
    if stage in _STAGE_TITLES:
        return _STAGE_TITLES[stage]
    return stage.replace("-", " ").replace("_", " ").capitalize()


def narrate_subject(trace, subject, with_values=True, width=76):
    """Return the narrative for one subject.

    >>> from ..core.trace import Trace
    >>> trace = Trace()
    >>> trace.record("progress", "03300", "25% complete through period 1")
    >>> trace.record("retainage-base", "03300", "base $100,000.00 under work_and_stored")
    >>> print(narrate_subject(trace, "03300"))
    03300
      Work in place
        25% complete through period 1
      Retainage base
        base $100,000.00 under work_and_stored
    """
    events = trace.for_subject(subject)
    if not events:
        raise DataError("nothing was recorded about %r" % (subject,))
    lines = [str(subject)]
    current = None
    for event in events:
        if event.stage != current:
            lines.append(indent(stage_title(event.stage), 2))
            current = event.stage
        text = event.render(with_values)
        text = text.split(": ", 1)[1] if ": " in text else text
        for wrapped in wrap(text, width - 4) or [text]:
            lines.append(indent(wrapped, 4))
    return "\n".join(lines)


def narrate(trace, subjects=None, stages=None, with_values=False):
    """Return the whole trace as a narrative, subject by subject.

    >>> from ..core.trace import Trace
    >>> trace = Trace()
    >>> trace.record("progress", "01000", "30% complete through period 1")
    >>> trace.record("progress", "03300", "25% complete through period 1")
    >>> print(narrate(trace))
    01000
      Work in place
        30% complete through period 1
    <BLANKLINE>
    03300
      Work in place
        25% complete through period 1
    """
    wanted = list(subjects) if subjects else trace.subjects()
    blocks = []
    for subject in wanted:
        events = trace.for_subject(subject)
        if stages:
            events = [event for event in events if event.stage in set(stages)]
        if not events:
            continue
        narrowed = _subtrace(trace, subject, stages)
        blocks.append(narrate_subject(narrowed, subject, with_values))
    return "\n\n".join(blocks)


def _subtrace(trace, subject, stages=None):
    """Return a trace holding one subject's events, optionally filtered."""
    from ..core.trace import Trace

    narrowed = Trace()
    for event in trace.for_subject(subject):
        if stages and event.stage not in set(stages):
            continue
        narrowed.record(event.stage, event.subject, event.message, event.values)
    return narrowed


def stage_summary(trace):
    """Return how many decisions each stage recorded, in stage order.

    >>> from ..core.trace import Trace
    >>> trace = Trace()
    >>> trace.record("progress", "01000", "a")
    >>> trace.record("progress", "03300", "b")
    >>> trace.record("stored", "26200", "c")
    >>> stage_summary(trace)
    [('progress', 2), ('stored', 1)]
    """
    counts = []
    for stage in trace.stages():
        counts.append((stage, len(trace.for_stage(stage))))
    return counts
