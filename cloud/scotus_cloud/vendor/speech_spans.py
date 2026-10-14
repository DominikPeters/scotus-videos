"""Remove the aligner's outer blank padding without removing internal blanks."""


def unpadded_spans(spans, blank):
    result = []
    for span in spans:
        first, last = 0, len(span)
        while first < last and span[first].label == blank:
            first += 1
        while last > first and span[last-1].label == blank:
            last -= 1
        # Star/empty targets can have no character frames. Preserve their
        # placeholder; the caller marks empty targets separately.
        result.append(span[first:last] if first < last else span)
    return result


def caption_start(padded_start, character_start, max_lead_seconds=.05):
    """Keep a small lead-in while preventing starts deep in a preceding pause."""
    if max_lead_seconds < 0:
        raise ValueError('Caption lead-in must be nonnegative')
    return max(padded_start, character_start-max_lead_seconds)
