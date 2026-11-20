"""Mono voice primitives for the audio-sampler-loop bugfix exercise.

Public audio data is always a mono ``list[float]``.  Every function follows
the contract documented on its docstring; invalid arguments raise
:class:`SamplerError`.
"""

from __future__ import annotations

import math

DEFAULT_SAMPLE_RATE = 44100.0


class SamplerError(ValueError):
    """Raised for invalid sampler parameters, loop points, or zones."""


def _valid_midi_note(note: int) -> bool:
    return isinstance(note, int) and 0 <= note <= 127


def pitch_ratio(root_note: int, note: int) -> float:
    """Return the playback frequency multiplier for a semitone interval.

    ``root_note`` and ``note`` are MIDI note numbers in ``0..127``.  The
    ratio is equal-tempered: ``2 ** ((note - root_note) / 12)``, so a unison
    is exactly ``1.0`` and one octave is exactly ``2.0``.  Results are
    compared with an absolute tolerance of ``1e-6``.  Invalid MIDI notes
    raise :class:`SamplerError`.
    """
    if not _valid_midi_note(root_note) or not _valid_midi_note(note):
        raise SamplerError(
            f"invalid MIDI notes: root_note={root_note!r}, note={note!r}"
        )
    return 2.0 ** ((note - root_note) / 12.0)


def loop_region(sample_len: int, loop_start: int, loop_end: int) -> tuple:
    """Validate a half-open sample loop and return ``(loop_start, loop_end)``.

    The loop region is ``[loop_start, loop_end)`` in frame indexes, where
    ``sample_len`` is the number of mono frames.  Require
    ``0 <= loop_start < loop_end <= sample_len``; otherwise raise
    :class:`SamplerError` (negative, out-of-bounds, inverted, or equal loop
    points are all invalid).  The returned tuple is unchanged and no samples
    are copied.  The loop end is exclusive and no crossfade is applied here.
    """
    if not (0 <= loop_start < loop_end <= sample_len):
        raise SamplerError(
            f"invalid loop region: sample_len={sample_len}, "
            f"loop_start={loop_start}, loop_end={loop_end}"
        )
    return (loop_start, loop_end)


def crossfade_loop(
    samples: list[float],
    loop_start: int,
    loop_end: int,
    fade: int,
) -> list[float]:
    """Return a click-free copy of ``samples`` with a crossfaded loop seam.

    Only the final ``fade`` frames of ``[loop_start, loop_end)`` are
    rewritten: they are linearly blended toward the first ``fade`` frames of
    the loop, so the last sample played before wrapping is close to the
    loop-start material.  ``loop_end`` is exclusive.  The result has exactly
    ``len(samples)`` frames, and frames outside that final fade window are
    copied unchanged.  ``fade=0`` returns an unchanged copy; empty input
    returns ``[]``.  Otherwise require a valid loop region and
    ``0 <= fade <= loop_end - loop_start``, raising :class:`SamplerError`
    when either is invalid.  Numeric comparisons use an absolute tolerance
    of ``1e-6``.
    """
    if not samples:
        return []
    if fade == 0:
        return list(samples)

    loop_region(len(samples), loop_start, loop_end)
    loop_len = loop_end - loop_start
    if not (isinstance(fade, int) and 0 <= fade <= loop_len):
        raise SamplerError(f"invalid fade length: fade={fade}")

    result = list(samples)
    # Blend the tail of the loop toward its head: the final frame becomes
    # identical to loop-start material, so the wrap has no discontinuity.
    for k in range(fade):
        target_index = loop_end - fade + k
        head_weight = (k + 1) / fade
        result[target_index] = (
            (1.0 - head_weight) * samples[target_index]
            + head_weight * samples[loop_start + k]
        )
    return result


def velocity_curve(velocity: float, curve: str) -> float:
    """Map a normalized velocity to a gain using ``curve``.

    ``velocity`` must be in ``[0.0, 1.0]``.  Supported curves are
    ``"linear"`` -> ``velocity``, ``"soft"`` -> ``velocity ** 1.5`` (more
    dynamic; quiet notes get quieter), and ``"hard"`` ->
    ``velocity ** 0.5`` (quiet notes get louder).  The result stays in
    ``[0.0, 1.0]`` and is compared with an absolute tolerance of ``1e-6``.
    An unknown curve or an out-of-range velocity raises
    :class:`SamplerError`.
    """
    if not (0.0 <= velocity <= 1.0):
        raise SamplerError(f"velocity out of range: {velocity!r}")
    if curve == "linear":
        return velocity
    if curve == "soft":
        return velocity ** 1.5
    if curve == "hard":
        return velocity ** 0.5
    raise SamplerError(f"unknown velocity curve: {curve!r}")


def _validate_zones(zones: list[dict]) -> None:
    """Validate zone shapes and reject overlapping (or touching) ranges."""
    for zone in zones:
        low = zone["low"]
        high = zone["high"]
        if not (isinstance(low, int) and isinstance(high, int) and low <= high):
            raise SamplerError(f"invalid zone bounds: {zone!r}")
    for i, zone_a in enumerate(zones):
        for zone_b in zones[i + 1:]:
            # Touching endpoints count as overlap, hence <= on both sides.
            if max(zone_a["low"], zone_b["low"]) <= min(
                zone_a["high"], zone_b["high"]
            ):
                raise SamplerError(
                    f"overlapping zones: {zone_a!r} and {zone_b!r}"
                )


def zone_lookup(zones: list[dict], note: int) -> dict:
    """Select the zone that owns ``note``, falling back to the nearest zone.

    ``zones`` is a sequence of dicts shaped
    ``{"root_note": int, "low": int, "high": int}`` with inclusive MIDI
    bounds.  All zones are validated first: ``low <= high`` and no two
    ranges may overlap (touching endpoints count as overlap), otherwise
    raise :class:`SamplerError`.

    If exactly one zone contains the note, return a shallow copy of that
    zone with ``fallback=False`` and ``fallback_semitones=0``.  If no zone
    contains it, choose the zone with the smallest distance to its range
    (note below ``low``: ``low - note``; note above ``high``:
    ``note - high``), breaking ties by the lower ``low``.  Return that copy
    with ``fallback=True`` and the distance in ``fallback_semitones``.  An
    empty ``zones`` sequence raises :class:`SamplerError`.
    """
    if not zones:
        raise SamplerError("no zones available for lookup")
    _validate_zones(zones)

    for zone in zones:
        if zone["low"] <= note <= zone["high"]:
            selected = dict(zone)
            selected["fallback"] = False
            selected["fallback_semitones"] = 0
            return selected

    def distance(zone: dict) -> int:
        if note < zone["low"]:
            return zone["low"] - note
        return note - zone["high"]

    nearest = min(zones, key=lambda zone: (distance(zone), zone["low"]))
    selected = dict(nearest)
    selected["fallback"] = True
    selected["fallback_semitones"] = distance(nearest)
    return selected


def render_voice(
    samples: list[float],
    note: int,
    duration: float,
    sample_rate: int,
    root_note: int,
) -> list[float]:
    """Render one mono voice for ``duration`` seconds at ``sample_rate`` Hz.

    The whole ``samples`` buffer is the loop body: source positions wrap with
    modulo indexing.  The playback step is
    ``pitch_ratio(root_note, note)`` source frames per output frame, using
    linear interpolation.  The target frame count is
    ``round(duration * sample_rate)``, computed once, so the output length is
    exact and does not drift for long notes (length error versus the
    mathematical duration is at most one sample).  Return exactly that many
    frames; empty ``samples`` returns ``[]``.  Require ``sample_rate > 0``,
    ``duration >= 0``, and MIDI notes in ``0..127``, otherwise raise
    :class:`SamplerError`.  Frames are treated as normalized ``-1.0..1.0``
    audio and compared with an absolute tolerance of ``1e-6``.
    """
    if sample_rate <= 0:
        raise SamplerError(f"sample_rate must be positive: {sample_rate!r}")
    if duration < 0:
        raise SamplerError(f"duration must be non-negative: {duration!r}")
    if not _valid_midi_note(note) or not _valid_midi_note(root_note):
        raise SamplerError(
            f"invalid MIDI notes: root_note={root_note!r}, note={note!r}"
        )
    if not samples:
        return []

    # Compute the exact frame count once: no per-frame truncation, no drift.
    frame_count = round(duration * sample_rate)
    ratio = pitch_ratio(root_note, note)
    source_len = len(samples)

    output: list[float] = []
    for frame_index in range(frame_count):
        position = frame_index * ratio
        base = math.floor(position)
        fraction = position - base
        index_a = base % source_len
        index_b = (base + 1) % source_len
        output.append(
            samples[index_a] * (1.0 - fraction)
            + samples[index_b] * fraction
        )
    return output


def release_tail(samples: list[float], loop_end: int, fade: int) -> list[float]:
    """Return a click-free release tail of exactly ``fade`` frames.

    The ``fade`` frames ending at the exclusive loop point
    (``samples[loop_end - fade:loop_end]``) are copied and multiplied by a
    linear fade-out envelope: gain ``1.0`` at the first frame down to
    ``0.0`` at the last frame.  ``fade=0`` returns ``[]``.  Require
    ``0 <= loop_end <= len(samples)`` and ``0 <= fade <= loop_end``,
    otherwise raise :class:`SamplerError`.  The returned length is always
    exactly ``fade`` and samples are compared with an absolute tolerance of
    ``1e-6``.
    """
    if not (0 <= loop_end <= len(samples)):
        raise SamplerError(f"loop_end out of range: {loop_end}")
    if not (isinstance(fade, int) and 0 <= fade <= loop_end):
        raise SamplerError(f"invalid fade length: fade={fade}")
    if fade == 0:
        return []

    source = samples[loop_end - fade:loop_end]
    if fade == 1:
        # The single frame is both first and last; keep it at unity so the
        # tail starts without a discontinuity.
        return [source[0]]
    return [
        source[i] * (fade - 1 - i) / (fade - 1)
        for i in range(fade)
    ]


def render_batch(notes: list[int], samples: list[float], zones: list[dict]) -> dict:
    """Render multiple notes transactionally while preserving request order.

    ``notes`` is a sequence of unique MIDI notes, ``samples`` is the mono
    loop body, and ``zones`` is the mapping accepted by
    :func:`zone_lookup`.  Each note is rendered for one full buffer pass at
    :data:`DEFAULT_SAMPLE_RATE`: the duration is
    ``len(samples) / DEFAULT_SAMPLE_RATE`` and every returned list has
    exactly ``len(samples)`` frames.  The matched zone's ``root_note``
    drives pitch, and every note starts from a fresh loop position, with no
    shared phase or mutable loop state between notes.

    Return a dict whose insertion order matches ``notes``.  Validate every
    note as a MIDI note in ``0..127`` and validate all zones before rendering
    anything; if any note, zone, or duplicate key is invalid, raise
    :class:`SamplerError` without exposing a partial dict.  Empty ``samples``
    returns a dict of empty lists for valid notes.
    """
    # Validate every note up front, including duplicate keys.
    for note in notes:
        if not _valid_midi_note(note):
            raise SamplerError(f"invalid MIDI note: {note!r}")
    if len(set(notes)) != len(notes):
        raise SamplerError(f"duplicate notes in batch: {notes!r}")

    # Resolve (and therefore validate) every zone before rendering anything,
    # so an invalid batch fails transactionally.
    matched_zones = [zone_lookup(zones, note) for note in notes]

    sample_rate = int(DEFAULT_SAMPLE_RATE)
    duration = len(samples) / DEFAULT_SAMPLE_RATE
    rendered: dict = {}
    for note, zone in zip(notes, matched_zones):
        # render_voice keeps all loop/phase state in locals, so each call
        # starts from position zero with no shared mutable state.
        rendered[note] = render_voice(
            samples,
            note,
            duration,
            sample_rate,
            zone["root_note"],
        )
    return rendered
