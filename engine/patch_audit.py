"""Record build writes and their overlap without exporting original game bytes.

This observes the accepted build; it is not an independent patch installer or
a proof of independence. Reads performed directly through RAM are not visible.
Last writer means last installer to touch a range, not necessarily its owner.
"""
import hashlib


class PatchAudit:

    def __init__(self):
        self.writes = []
        self.spans = []  # Non-overlapping (start, end, write index).

    def record(self, revision, module, start, before, after):
        if len(before) != len(after) or start < 0:
            raise ValueError('Invalid audited write')
        if not after:
            return
        end = start + len(after)
        index = len(self.writes)
        spans, overlap = [], []
        for lo, hi, writer in self.spans:
            if hi <= start or lo >= end:
                spans.append((lo, hi, writer))
                continue
            overlap.append(dict(write=writer, start=max(lo, start), end=min(hi, end)))
            if lo < start:
                spans.append((lo, start, writer))
            if hi > end:
                spans.append((end, hi, writer))
        spans.append((start, end, index))
        self.spans = sorted(spans)
        digest = lambda b: hashlib.sha256(b).hexdigest()
        self.writes.append(
            dict(
                revision=revision,
                module=module,
                start=start,
                end=end,
                changed=before != after,
                before_sha256=digest(before),
                after_sha256=digest(after),
                previous_writers=overlap
            )
        )

    def report(self):
        return dict(
            schema=1,
            scope='Accepted v38+ build writes; foundation is not traced',
            limitations=[
                'Raw RAM reads are not traced; overlaps do not prove dependencies.',
                'Last write includes idempotent writes, padding and version labels.',
                'Reservations and runtime writes need separate review.'
            ],
            writes=self.writes,
            final_spans=[dict(start=a, end=b, write=w) for a, b, w in self.spans]
        )
