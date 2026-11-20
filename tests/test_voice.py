"""Red-state tests for the audio sampler exercise.

Every test calls a public stub in ``sampler.voice``.  With the stubs in
place all 15 tests fail; they are not expected to be edited.
"""

from __future__ import annotations

import pytest

from sampler.voice import (
    SamplerError,
    crossfade_loop,
    loop_region,
    pitch_ratio,
    release_tail,
    render_batch,
    render_voice,
    velocity_curve,
    zone_lookup,
)


def test_pitch_ratio_uses_semitone_octaves():
    """Defect 1: a semitone interval must be exponential, not linear."""
    assert pitch_ratio(60, 72) == pytest.approx(2.0, abs=1e-6)
    assert pitch_ratio(60, 67) == pytest.approx(2 ** (7 / 12), abs=1e-6)


def test_crossfade_loop_removes_seam_click():
    """Defect 2: the loop seam needs a crossfade instead of a hard jump."""
    samples = [0.0, 0.1, 0.2, 0.3, 0.9, 1.0, 0.8, 0.7]
    loop_start, loop_end, fade = 2, 6, 2
    faded = crossfade_loop(samples, loop_start, loop_end, fade)

    assert len(faded) == len(samples)
    assert faded[: loop_end - fade] == samples[: loop_end - fade]
    assert abs(faded[loop_end - 1] - faded[loop_start]) < abs(
        samples[loop_end - 1] - samples[loop_start]
    )
    assert max(abs(value) for value in faded) <= 1.0


def test_loop_region_rejects_inverted_range():
    """Defect 3: a loop whose start is after its end must be rejected."""
    with pytest.raises(SamplerError):
        loop_region(64, 40, 20)


def test_velocity_curve_makes_soft_notes_dynamic():
    """Defect 4: soft playing must not use the same linear curve as hard."""
    linear = velocity_curve(0.25, "linear")
    soft = velocity_curve(0.25, "soft")
    hard = velocity_curve(0.25, "hard")

    assert linear == pytest.approx(0.25, abs=1e-6)
    assert soft < linear < hard
    assert 0.0 <= soft <= hard <= 1.0


def test_zone_lookup_falls_back_to_nearest_zone():
    """Defect 5: a note in a gap must use and mark the nearest zone."""
    zones = [
        {"root_note": 48, "low": 36, "high": 47},
        {"root_note": 60, "low": 48, "high": 59},
        {"root_note": 72, "low": 72, "high": 83},
    ]

    selected = zone_lookup(zones, 65)

    assert selected["root_note"] == 60
    assert selected["low"] == 48
    assert selected["high"] == 59
    assert selected["fallback"] is True
    assert selected["fallback_semitones"] == 6


def test_render_voice_length_stable_for_long_notes():
    """Defect 6: long renders must not accumulate a fractional frame error."""
    samples = [0.0, 0.25, 0.5, 0.75, 1.0, 0.75, 0.5, 0.25]

    short = render_voice(samples, 60, 0.5, 44100, 60)
    long = render_voice(samples, 60, 10.0, 44100, 60)

    assert len(short) == 22050
    assert len(long) == 441000


def test_release_tail_fades_to_silence():
    """Defect 7: the release must fade out rather than cut off abruptly."""
    samples = [0.25, 0.5, 0.75, 1.0, 1.0, 1.0, 1.0, 1.0]

    tail = release_tail(samples, loop_end=8, fade=4)

    assert len(tail) == 4
    assert tail[0] == pytest.approx(1.0, abs=1e-6)
    assert tail[-1] == pytest.approx(0.0, abs=1e-6)
    assert all(left >= right - 1e-6 for left, right in zip(tail, tail[1:]))


def test_loop_region_rejects_out_of_bounds():
    """Defect 8: loop points outside the sample buffer must raise, not index."""
    with pytest.raises(SamplerError):
        loop_region(100, 90, 101)
    with pytest.raises(SamplerError):
        loop_region(100, -1, 50)


def test_render_batch_isolates_each_note():
    """Defect 9: each batch voice must start with fresh loop state."""
    samples = [0.0, 0.25, 0.5, 0.75, 1.0, 0.75, 0.5, 0.25]
    zones = [
        {"root_note": 60, "low": 48, "high": 71},
        {"root_note": 72, "low": 72, "high": 84},
    ]

    combined = render_batch([55, 79], samples, zones)
    solo_low = render_batch([55], samples, zones)[55]
    solo_high = render_batch([79], samples, zones)[79]

    assert combined[55] == solo_low
    assert combined[79] == solo_high
    assert combined[55] != combined[79]

    # A rejected note must abort the whole batch without poisoning later work.
    with pytest.raises(SamplerError):
        render_batch([55, 128], samples, zones)
    assert render_batch([55], samples, zones)[55] == solo_low


def test_zone_lookup_rejects_overlapping_zones():
    """Defect 10: overlapping key ranges are ambiguous and must raise."""
    zones = [
        {"root_note": 60, "low": 48, "high": 60},
        {"root_note": 64, "low": 60, "high": 72},
    ]

    with pytest.raises(SamplerError):
        zone_lookup(zones, 60)


def test_note_at_root_has_unit_ratio():
    """Combination: a note at its own root plays at unity speed."""
    assert pitch_ratio(60, 60) == pytest.approx(1.0, abs=1e-6)
    assert pitch_ratio(21, 21) == pytest.approx(1.0, abs=1e-6)


def test_zero_fade_leaves_samples_unchanged():
    """Combination: fade=0 is an exact no-op copy."""
    samples = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 0.8, 0.6]

    assert crossfade_loop(samples, 2, 6, 0) == samples


def test_loop_region_rejects_equal_points():
    """Combination: an empty loop has no playable frames and must raise."""
    with pytest.raises(SamplerError):
        loop_region(64, 32, 32)


def test_empty_samples_return_empty():
    """Combination: empty input is a valid empty render, not an index error."""
    assert crossfade_loop([], 0, 0, 0) == []
    assert render_voice([], 60, 1.0, 44100, 60) == []


def test_render_batch_preserves_note_order():
    """Combination: a fully successful batch keeps the requested key order."""
    samples = [0.0, 0.25, 0.5, 0.75, 1.0, 0.75, 0.5, 0.25]
    zones = [
        {"root_note": 60, "low": 48, "high": 71},
        {"root_note": 72, "low": 72, "high": 84},
    ]
    notes = [67, 60, 72, 55]

    rendered = render_batch(notes, samples, zones)

    assert list(rendered.keys()) == notes
    assert all(len(rendered[note]) == len(samples) for note in notes)
