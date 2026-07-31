import os
import librosa
import numpy as np
from scipy.signal import butter, lfilter, fftconvolve

# ---------- Basic DSP helpers ----------

def _fade_in_out(y, sr, fade_seconds=1.0):
    n = len(y)
    fade_len = int(fade_seconds * sr)
    if fade_len <= 0 or fade_len * 2 > n:
        return y

    fade_in = np.linspace(0.0, 1.0, fade_len)
    fade_out = np.linspace(1.0, 0.0, fade_len)

    env = np.ones(n)
    env[:fade_len] *= fade_in
    env[-fade_len:] *= fade_out
    return y * env


def _crossfade(y1, y2, sr, fade_seconds=2.0):
    """
    Smoothly blend the tail of y1 into the head of y2 using an
    equal-power (squared) crossfade over the overlap region.

    The overlap is taken from the *end* of y1 and the *start* of y2:
      - y1's last `fade_len` samples are faded out
      - y2's first `fade_len` samples are faded in
      - the two are summed in the overlap zone

    The returned array is shorter than y1+y2 by `fade_len` samples,
    which preserves natural song timing (the overlap "absorbs" time
    from both sides rather than inserting silence).

    Edge cases
    ----------
    - If either section is empty, the other is returned as-is.
    - If either section is shorter than `fade_len`, the fade is
      automatically shortened to fit the shortest section.

    Parameters
    ----------
    y1 : np.ndarray   – first audio segment
    y2 : np.ndarray   – second audio segment
    sr : int          – sample rate
    fade_seconds : float – duration of the crossfade overlap (default 2 s)
    """
    n1 = len(y1)
    n2 = len(y2)

    # --- trivial / empty cases ---
    if n1 == 0:
        return y2
    if n2 == 0:
        return y1

    fade_len = int(fade_seconds * sr)

    # Clamp fade length so it never exceeds either section
    fade_len = min(fade_len, n1, n2)

    if fade_len <= 0:
        return np.concatenate([y1, y2])

    # --- Build equal-power (squared) fade curves ---
    # Squared curves sum to ~1.0, avoiding the ~-3 dB dip
    # that linear crossfades produce in the middle.
    ramp = np.linspace(0.0, 1.0, fade_len)
    fade_out = (1.0 - ramp) ** 2   # y1 fades out
    fade_in  = ramp ** 2            # y2 fades in

    # --- Assemble: [y1_head | overlap | y2_tail] ---
    y1_head = y1[:n1 - fade_len]                      # before overlap
    y1_tail = y1[n1 - fade_len:]                      # will fade out
    y2_head = y2[:fade_len]                            # will fade in
    y2_tail = y2[fade_len:]                            # after overlap

    overlap = y1_tail * fade_out + y2_head * fade_in

    return np.concatenate([y1_head, overlap, y2_tail])


# --- helper to smooth reverb tail (remove harsh hiss) ---

def _smooth_tail(tail, sr, cutoff=6000):
    """
    Light low-pass filter on the artificial reverb tail to reduce
    high-frequency 'radio noise' feeling.
    """
    nyq = 0.5 * sr
    norm_cut = cutoff / nyq
    b, a = butter(2, norm_cut, btype="low", analog=False)
    return lfilter(b, a, tail)


def _reverb(y, sr, amount=0.0):
    """
    Simple lush reverb:
    - noise-based tail shaped with exponential decay
    - tail is low-passed for smoother, less 'broken' sound
    - 'amount' is wet/dry mix 0-1
    """
    if amount <= 0.0:
        return y

    # 1.5–3.0s tail depending on amount
    tail_seconds = 1.5 + 1.5 * amount
    tail_len = int(tail_seconds * sr)
    if tail_len <= 0:
        return y

    t = np.linspace(0, 1, tail_len)
    decay_curve = np.exp(-3.5 * t)
    tail = np.random.randn(tail_len) * decay_curve

    # soften highs of the tail to avoid harsh hiss
    tail = _smooth_tail(tail, sr, cutoff=6000)

    wet = fftconvolve(y, tail, mode="full")[:len(y)]
    wet = wet / (np.max(np.abs(wet)) + 1e-6)

    # more wet mix for higher amount
    wet_mix = 0.2 + 0.6 * amount  # 0.2–0.8
    dry_mix = 1.0 - wet_mix

    out = dry_mix * y + wet_mix * wet

    peak = np.max(np.abs(out)) + 1e-6
    out = out / peak * 0.98
    return out


def _sub_woofer_boost(y, sr, amount=0.0):
    if amount <= 0.0:
        return y
    
    nyq = 0.5 * sr
    norm_cut = 80.0 / nyq
    b, a = butter(4, norm_cut, btype="low", analog=False)
    
    sub_bass = lfilter(b, a, y)
    sub_bass = np.tanh(sub_bass * 3.0) * (amount * 0.5)
    
    y_out = y + sub_bass
    peak_out = np.max(np.abs(y_out)) + 1e-6
    if peak_out > 1.0:
        y_out = y_out / peak_out * 0.98
        
    return y_out

# ---------- Bitcrusher ----------

def _bitcrusher(y, amount=0.0):
    if amount <= 0.0:
        return y
    
    # Map amount (0-1) to bits (16 down to 2)
    # Higher amount = fewer bits = more crunch
    bits = max(2, int(16 - (14 * amount)))
    steps = 2 ** bits
    
    # Quantize amplitude
    y_crush = np.round(y * steps) / steps
    
    # Simulate downsampling (sample-and-hold)
    # Higher amount = lower sample rate = more aliasing
    downsample_factor = max(1, int(amount * 10))
    if downsample_factor > 1:
        # Create an array of indices that repeat the held value
        indices = (np.arange(len(y_crush)) // downsample_factor) * downsample_factor
        y_crush = y_crush[indices]
        
    return y_crush

# ---------- 8D Audio (Auto-Panning) ----------

def _apply_8d_audio(y, sr, amount=0.0):
    if amount <= 0.0:
        return y
        
    # Ensure audio is 2D stereo array
    if y.ndim == 1:
        y_stereo = np.vstack((y, y))
    else:
        y_stereo = y.copy()
        
    n = y_stereo.shape[1]
    
    # Slow LFO sine wave (0.15 Hz)
    freq = 0.15
    t = np.arange(n) / sr
    
    # LFO ranges from -1 to 1, scaled by amount
    lfo = np.sin(2 * np.pi * freq * t) * amount
    
    # Pan modulation: Left channel decreases when Right increases
    left_mod = np.clip(1.0 - max(0, lfo), 0, 1) if np.isscalar(lfo) else np.clip(1.0 - np.maximum(0, lfo), 0, 1)
    right_mod = np.clip(1.0 - max(0, -lfo), 0, 1) if np.isscalar(lfo) else np.clip(1.0 - np.maximum(0, -lfo), 0, 1)
    # actually a simpler math:
    left_gain = 1.0 - np.clip(lfo, 0, 1)
    right_gain = 1.0 - np.clip(-lfo, 0, 1)
    
    y_stereo[0, :] *= left_gain
    y_stereo[1, :] *= right_gain
    
    return y_stereo

# ---------- Wow & Flutter (tape speed modulation) ----------

def _wow_and_flutter(y, sr, amount=0.0):
    """
    Authentic vintage tape speed modulation via fractional-delay interpolation.

    Instead of pitch-shifting frame-by-frame (very slow), we warp the
    timeline itself using two superimposed LFOs:

      - Wow  (slow ~0.5 Hz): broad, gentle pitch drift caused by capstan
        eccentricity or belt stretch in a tape deck.
      - Flutter (fast ~6 Hz): rapid micro-variations from motor cogging
        and guide-roller irregularities.

    The combined LFO produces a time-varying fractional sample offset.
    We build a warped read-pointer array and use numpy linear interpolation
    to resample — all in a single vectorised pass, O(N).

    Parameters
    ----------
    y : np.ndarray   – mono audio signal
    sr : int         – sample rate
    amount : float   – 0.0 (off) to 1.0 (heavy wobble)
    """
    if amount <= 0.0:
        return y

    n = len(y)
    t = np.arange(n, dtype=np.float64)

    # --- LFO 1: Wow (slow drift) ---
    # Frequency ~0.5 Hz; max depth = ±40 samples at 44.1 kHz ≈ ±0.9 ms
    wow_freq = 0.5                          # Hz
    wow_depth = amount * 40.0 * (sr / 44100)  # scale depth to sample rate
    wow_lfo = wow_depth * np.sin(2.0 * np.pi * wow_freq * t / sr)

    # --- LFO 2: Flutter (rapid micro-variation) ---
    # Frequency ~6 Hz; max depth = ±10 samples at 44.1 kHz ≈ ±0.23 ms
    flutter_freq = 6.0                      # Hz
    flutter_depth = amount * 10.0 * (sr / 44100)
    flutter_lfo = flutter_depth * np.sin(2.0 * np.pi * flutter_freq * t / sr)

    # --- Combined warped read pointer ---
    # Each output sample i reads from source position i + lfo(i).
    # Positive offset = momentarily slower playback (pitch drops).
    warped = t + wow_lfo + flutter_lfo

    # Clamp to valid source indices
    warped = np.clip(warped, 0, n - 1)

    # --- Fractional-delay resample via linear interpolation ---
    y_out = np.interp(warped, t, y).astype(np.float32)

    return y_out


# ---------- Vinyl Crackle overlay ----------

def _add_crackle(y, sr, amount=0.0):
    """
    Mix a vinyl-crackle texture onto the signal.

    Tries to load bgm_core/crackle.wav first; if that file is missing,
    synthesises crackle procedurally using Poisson-distributed impulses
    convolved with a short decaying click kernel, then low-passed for
    warmth.  The crackle is tiled to match signal length, scaled by
    `amount`, and summed onto the dry signal.

    Parameters
    ----------
    y : np.ndarray   – mono audio signal
    sr : int         – sample rate
    amount : float   – 0.0 (off) to 1.0 (loud crackle)
    """
    if amount <= 0.0:
        return y

    n = len(y)
    crackle = None

    # --- Attempt to load crackle.wav ---
    crackle_path = os.path.join(os.path.dirname(__file__), "crackle.wav")
    if os.path.isfile(crackle_path):
        try:
            crackle, _ = librosa.load(crackle_path, sr=sr, mono=True)
        except Exception:
            crackle = None

    # --- Procedural fallback: synthesise crackle ---
    if crackle is None:
        # Average ~200 clicks/sec, scaled by amount for density
        click_density = 200 * amount
        # Poisson process: inter-click intervals are exponentially distributed
        rng = np.random.default_rng(42)  # deterministic seed for consistency
        intervals = rng.exponential(sr / click_density, size=int(click_density * (n / sr) * 2))
        click_positions = np.cumsum(intervals).astype(int)
        click_positions = click_positions[click_positions < n]

        crackle = np.zeros(n, dtype=np.float32)
        # Each click is a short exponentially-decaying impulse (~1 ms)
        click_len = max(1, int(0.001 * sr))
        click_kernel = np.exp(-np.linspace(0, 5, click_len)).astype(np.float32)

        for pos in click_positions:
            end = min(pos + click_len, n)
            seg = end - pos
            # Random polarity and amplitude
            amp = rng.uniform(0.3, 1.0)
            sign = rng.choice([-1.0, 1.0])
            crackle[pos:end] += sign * amp * click_kernel[:seg]

        # Low-pass at ~4 kHz for warmth
        nyq = 0.5 * sr
        if nyq > 4000:
            norm_cut = 4000 / nyq
            b, a = butter(2, norm_cut, btype="low", analog=False)
            crackle = lfilter(b, a, crackle).astype(np.float32)

    # --- Tile / trim crackle to match signal length ---
    if len(crackle) < n:
        reps = int(np.ceil(n / len(crackle)))
        crackle = np.tile(crackle, reps)[:n]
    else:
        crackle = crackle[:n]

    # Normalise crackle to unit peak, then scale by amount
    peak = np.max(np.abs(crackle)) + 1e-8
    crackle = crackle / peak * amount * 0.45  # 0.45 gives prominent warmth at max

    y_out = y + crackle
    # Soft-clip to prevent overs
    peak_out = np.max(np.abs(y_out)) + 1e-6
    if peak_out > 1.0:
        y_out = y_out / peak_out * 0.98

    return y_out


# ---------- Fast Reverb (Schroeder delay-line network) ----------

def _fast_reverb(y, sr, amount=0.0):
    """
    Schroeder-style artificial reverb using a network of comb and all-pass
    delay lines.  Runs in O(N) with tiny constant — dramatically faster
    than the full-length fftconvolve reverb for tracks over ~30 seconds.

    Structure
    ---------
    4 parallel comb filters  →  summed  →  2 cascaded all-pass filters

    Comb delays are chosen as prime-ish multiples of samples to avoid
    resonance pile-up.  Feedback gains produce a natural-sounding decay
    of roughly 1–3 seconds depending on `amount`.

    Parameters
    ----------
    y : np.ndarray   – mono audio signal
    sr : int         – sample rate
    amount : float   – 0.0 (off) to 1.0 (heavy reverb)
    """
    if amount <= 0.0:
        return y

    n = len(y)

    # --- Comb filter delays (in seconds) and base feedback gains ---
    comb_delays_sec = [0.0297, 0.0371, 0.0411, 0.0437]  # ~29-44 ms
    comb_base_gains = [0.74, 0.78, 0.80, 0.82]

    def _comb_filter(x, delay_samples, feedback):
        """IIR comb: y[n] = x[n] + feedback * y[n - delay]"""
        out = np.zeros(len(x), dtype=np.float64)
        d = int(delay_samples)
        for i in range(len(x)):
            out[i] = x[i]
            if i >= d:
                out[i] += feedback * out[i - d]
        return out

    def _allpass_filter(x, delay_samples, gain):
        """Schroeder all-pass: y[n] = -g*x[n] + x[n-d] + g*y[n-d]"""
        out = np.zeros(len(x), dtype=np.float64)
        d = int(delay_samples)
        g = gain
        for i in range(len(x)):
            x_delayed = x[i - d] if i >= d else 0.0
            y_delayed = out[i - d] if i >= d else 0.0
            out[i] = -g * x[i] + x_delayed + g * y_delayed
        return out

    # Scale feedback by amount (more amount = longer tail)
    comb_sum = np.zeros(n, dtype=np.float64)
    for delay_sec, base_gain in zip(comb_delays_sec, comb_base_gains):
        delay_samps = int(delay_sec * sr)
        fb = base_gain * (0.7 + 0.3 * amount)  # range ~0.52–0.85
        comb_sum += _comb_filter(y.astype(np.float64), delay_samps, fb)

    comb_sum /= 4.0  # average the 4 combs

    # --- All-pass diffusion ---
    ap1_delay = int(0.005 * sr)   # ~5 ms
    ap2_delay = int(0.0017 * sr)  # ~1.7 ms
    ap_gain = 0.7

    diffused = _allpass_filter(comb_sum, ap1_delay, ap_gain)
    diffused = _allpass_filter(diffused, ap2_delay, ap_gain)

    # --- Wet/dry mix ---
    wet_mix = 0.2 + 0.6 * amount   # 0.2–0.8
    dry_mix = 1.0 - wet_mix

    # Normalise wet signal
    wet_peak = np.max(np.abs(diffused)) + 1e-6
    diffused = diffused / wet_peak

    out = dry_mix * y.astype(np.float64) + wet_mix * diffused
    peak = np.max(np.abs(out)) + 1e-6
    out = (out / peak * 0.98).astype(np.float32)

    return out


# ---------- Simple bass / highs / lofi ----------

def _bass_boost(y, sr, amount=0.0):
    """
    Simple, musical bass boost.
    - Focused low-shelf style around ~120 Hz.
    - Always adds some bass when amount > 0.
    """
    if amount <= 0.0:
        return y

    # Small headroom
    y_work = y * 0.9  # ~ -1 dB

    def low_shelf_like(data, cutoff=120, gain_db=12.0, order=4):
        nyq = 0.5 * sr
        norm_cut = cutoff / nyq
        b, a = butter(order, norm_cut, btype="low", analog=False)
        low = lfilter(b, a, data)
        g = 10 ** (gain_db / 20.0)
        return data + (g - 1.0) * low

    # Map 0–1 → 0–15 dB
    gain_db = 0.0 + 15.0 * amount
    y_boost = low_shelf_like(y_work, gain_db=gain_db)

    peak = np.max(np.abs(y_boost)) + 1e-6
    y_boost = y_boost / peak * 0.98
    return y_boost


def _high_boost(y, sr, amount=0.0):
    if amount <= 0.0:
        return y

    def highpass(data, cutoff=2000, order=4):
        nyq = 0.5 * sr
        normal_cutoff = cutoff / nyq
        b, a = butter(order, normal_cutoff, btype="high", analog=False)
        return lfilter(b, a, data)

    high = highpass(y)
    boosted = y + amount * high
    max_val = np.max(np.abs(boosted)) + 1e-6
    boosted = boosted / max_val * 0.95
    return boosted


def _lofi_filter(y, sr, amount=0.0):
    if amount <= 0.0:
        return y

    def lowpass(data, cutoff=2500, order=4):
        nyq = 0.5 * sr
        normal_cutoff = cutoff / nyq
        b, a = butter(order, normal_cutoff, btype="low", analog=False)
        return lfilter(b, a, data)

    filt = lowpass(y)
    out = (1 - amount) * y + amount * filt
    max_val = np.max(np.abs(out)) + 1e-6
    out = out / max_val * 0.95
    return out


def _reverse_audio(y):
    return y[::-1]

# ---------- Section processor (EQ / filtering only) ----------

def _process_section_eq(y, sr, bass_amount, high_amount, lofi_amount):
    """
    Per-section EQ and filtering chain.
    Reverb is intentionally excluded here — it is applied globally
    after sections are crossfaded to avoid phase discontinuities
    and click artifacts at section boundaries.
    """
    y = _bass_boost(y, sr, amount=bass_amount)
    y = _high_boost(y, sr, amount=high_amount)
    y = _lofi_filter(y, sr, amount=lofi_amount)
    return y

# ---------- Main remix with 3 sections + optional segment ----------

def remix_audio(
    file,
    speed: float = 1.0,
    pitch_steps: int = 0,
    fade_flag: bool = True,
    reverse_flag: bool = False,
    # section times in seconds (relative to processed audio)
    t1: float = 30.0,
    t2: float = 60.0,
    # section 1 params
    bass1: float = 0.2,
    high1: float = 0.2,
    reverb1: float = 0.2,
    lofi1: float = 0.0,
    # section 2 params
    bass2: float = 0.7,
    high2: float = 0.4,
    reverb2: float = 0.3,
    lofi2: float = 0.1,
    # section 3 params
    bass3: float = 0.35,
    high3: float = 0.2,
    reverb3: float = 0.4,
    lofi3: float = 0.4,
    # optional segment preview
    start_time: float = 0.0,
    duration: float | None = None,
    # --- DSP parameters ---
    wow_flutter_amount: float = 0.0,
    crackle_amount: float = 0.0,
    use_fast_reverb: bool = False,
    enable_sections: bool = True,
    transition_style: str = "Smooth Crossfade",
    sub_woofer_amount: float = 0.0,
    bitcrush_amount: float = 0.0,
    audio_8d_amount: float = 0.0,
    track_2_file=None,
    track_2_volume: float = 0.0,
    track_2_start_delay: float = 0.0,
    track_2_mode: str = "Overlay (Mashup)",
    track_2_in_point: float = 0.0,
    crossfade_sec: float = 3.5,
    return_to_track_1: bool = False,
    track_2_out_point: float = None,
    track_1_resume_point: float = 120.0,
):
    """
    DJ-style remix of existing audio with 3 timeline sections.

    Order of operations (refactored to eliminate transition artifacts):
      1. Load & optional preview crop
      2. Section slicing + per-section EQ/filtering (bass, highs, lofi)
         → crossfade stitch into y_out  (skipped when enable_sections=False)
      3. Global speed & pitch shift (on full y_out)
      4. Global reverse
      5. Global Wow & Flutter
      6. Global Reverb (convolution or Schroeder)
      7. Global Vinyl Crackle
      8. Final fade in/out & peak normalisation

    Reverb, wow/flutter, and crackle are applied globally AFTER sections
    are stitched to prevent phase discontinuities and click artefacts
    at crossfade boundaries.
    """

    # Make sure file pointer is at start for Streamlit uploads
    try:
        file.seek(0)
    except Exception:
        pass

    y, sr = librosa.load(file, sr=None, mono=True)

    # Optional segment crop BEFORE any processing (for fast preview)
    if duration is not None and duration > 0:
        n = len(y)
        total_dur_orig = n / sr
        start_time = max(0.0, min(start_time, max(0.0, total_dur_orig - duration)))
        i_start = int(start_time * sr)
        i_end = int((start_time + duration) * sr)
        y = y[i_start:i_end]

    n = len(y)
    if n == 0:
        return y, sr

    # ── Step 2: Conditional section processing (EQ only) ──────────
    if enable_sections:
        total_dur = n / sr

        # Clamp section times
        t1 = max(0.0, min(t1, total_dur))
        t2 = max(t1, min(t2, total_dur))

        i1 = int(t1 * sr)
        i2 = int(t2 * sr)

        # Split into 3 sections
        y1 = y[:i1]
        y2 = y[i1:i2]
        y3 = y[i2:]

        # Apply per-section EQ/filtering only (no reverb, no time effects)
        if len(y1) > 0:
            y1 = _process_section_eq(y1, sr, bass1, high1, lofi1)
        if len(y2) > 0:
            y2 = _process_section_eq(y2, sr, bass2, high2, lofi2)
        if len(y3) > 0:
            y3 = _process_section_eq(y3, sr, bass3, high3, lofi3)

        if transition_style == "Hard Beat Drop":
            silence = np.zeros(int(0.15 * sr), dtype=np.float32)
            y_out = np.concatenate([y1, silence, y2, silence, y3])
        else:
            # Smooth crossfade stitch (default overlap duration)
            y_out = _crossfade(y1, y2, sr, fade_seconds=crossfade_sec)
            y_out = _crossfade(y_out, y3, sr, fade_seconds=crossfade_sec)

        # Derive a single global reverb amount from the per-section sliders
        # (weighted by approximate section duration to preserve user intent)
        dur1 = max(len(y1), 1)
        dur2 = max(len(y2), 1)
        dur3 = max(len(y3), 1)
        total_weight = dur1 + dur2 + dur3
        reverb_amount = (
            reverb1 * dur1 + reverb2 * dur2 + reverb3 * dur3
        ) / total_weight
    else:
        # Bypass section processing entirely
        y_out = y.copy()
        # Use a simple average of reverb sliders as the global amount
        reverb_amount = (reverb1 + reverb2 + reverb3) / 3.0

    # ── Step 3: Global speed & pitch ──────────────────────────────
    # Clamp to musical ranges to keep quality
    speed = float(np.clip(speed, 0.6, 1.3))
    pitch_steps = int(np.clip(pitch_steps, -7, 7))

    if speed != 1.0:
        y_out = librosa.effects.time_stretch(y_out, rate=speed)
    if pitch_steps != 0:
        y_out = librosa.effects.pitch_shift(y_out, sr=sr, n_steps=pitch_steps)

    # ── Step 4: Global reverse ────────────────────────────────────
    if reverse_flag:
        y_out = _reverse_audio(y_out)

    # ── Step 5: Global Wow & Flutter ──────────────────────────────
    if wow_flutter_amount > 0.0:
        y_out = _wow_and_flutter(y_out, sr, amount=wow_flutter_amount)

    # ── Step 6: Global Reverb ─────────────────────────────────────
    if reverb_amount > 0.0:
        if use_fast_reverb:
            y_out = _fast_reverb(y_out, sr, amount=reverb_amount)
        else:
            y_out = _reverb(y_out, sr, amount=reverb_amount)

    # ── Step 7: Global Vinyl Crackle ──────────────────────────────
    if crackle_amount > 0.0:
        y_out = _add_crackle(y_out, sr, amount=crackle_amount)

    # ── Step 7.5: Sub-Woofer Boost ────────────────────────────────
    if sub_woofer_amount > 0.0:
        y_out = _sub_woofer_boost(y_out, sr, amount=sub_woofer_amount)

    # ── Step 7.6: Bitcrusher ──────────────────────────────────────
    if bitcrush_amount > 0.0:
        y_out = _bitcrusher(y_out, amount=bitcrush_amount)

    # ── Step 7.7: 8D Audio (Auto-Panning) ─────────────────────────
    if audio_8d_amount > 0.0:
        y_out = _apply_8d_audio(y_out, sr, amount=audio_8d_amount)

    # ── Step 7.8: Mashup / Layer Track 2 ──────────────────────────
    if track_2_file is not None and track_2_volume > 0.0:
        try:
            track_2_file.seek(0)
        except Exception:
            pass
        y2_layer, sr2 = librosa.load(track_2_file, sr=sr, mono=True)
        if len(y2_layer) > 0:
            start_idx = int(track_2_in_point * sr)
            if track_2_out_point is not None and track_2_out_point > track_2_in_point:
                end_idx = int(track_2_out_point * sr)
            else:
                end_idx = len(y2_layer)
            
            start_idx = max(0, min(start_idx, len(y2_layer)))
            end_idx = max(start_idx, min(end_idx, len(y2_layer)))
            
            y2_layer = y2_layer[start_idx:end_idx]

            # Auto-beatmatch
            bpm1, _ = librosa.beat.beat_track(y=y_out if y_out.ndim == 1 else y_out[0], sr=sr)
            bpm2, _ = librosa.beat.beat_track(y=y2_layer, sr=sr)
            
            # Ensure bpm is a scalar float. librosa.beat.beat_track returns a float or an array depending on versions.
            bpm1 = float(bpm1[0]) if isinstance(bpm1, np.ndarray) else float(bpm1)
            bpm2 = float(bpm2[0]) if isinstance(bpm2, np.ndarray) else float(bpm2)
            
            if bpm1 > 0 and bpm2 > 0:
                stretch_rate = bpm1 / bpm2
                y2_layer = librosa.effects.time_stretch(y2_layer, rate=stretch_rate)
            
            if track_2_mode == "Overlay (Mashup)":
                # Alignment (Delay)
                delay_samples = int(track_2_start_delay * sr)
                if delay_samples > 0:
                    silence = np.zeros(delay_samples, dtype=np.float32)
                    y2_layer = np.concatenate([silence, y2_layer])
                    
                # If 8D converted main track to stereo, we must convert y2_layer to stereo
                if y_out.ndim == 2:
                    y2_layer = np.vstack((y2_layer, y2_layer))
                    
                # Length Matching
                len1 = y_out.shape[1] if y_out.ndim == 2 else len(y_out)
                len2 = y2_layer.shape[1] if y2_layer.ndim == 2 else len(y2_layer)
                
                if len2 < len1:
                    if y_out.ndim == 2:
                        pad = np.zeros((2, len1 - len2), dtype=np.float32)
                        y2_layer = np.hstack((y2_layer, pad))
                    else:
                        pad = np.zeros(len1 - len2, dtype=np.float32)
                        y2_layer = np.concatenate([y2_layer, pad])
                elif len2 > len1:
                    if y_out.ndim == 2:
                        y2_layer = y2_layer[:, :len1]
                    else:
                        y2_layer = y2_layer[:len1]
                        
                # Mixing
                y_out = y_out + (y2_layer * track_2_volume)
            else:
                # Switch (DJ Cut to Track 2)
                switch_idx = int(track_2_start_delay * sr)
                
                # Save full backup before cutting
                y_out_full = np.copy(y_out)
                
                # Cut y_out
                if y_out.ndim == 2:
                    y1_part = y_out[:, :switch_idx]
                else:
                    y1_part = y_out[:switch_idx]
                
                # Apply volume to Track 2
                y2_part = y2_layer * track_2_volume
                
                if y1_part.ndim == 2:
                    y2_part = np.vstack((y2_part, y2_part))
                
                if return_to_track_1:
                    resume_idx = int(track_1_resume_point * sr)
                    if y_out_full.ndim == 2:
                        track_1_part_2 = y_out_full[:, resume_idx:]
                    else:
                        track_1_part_2 = y_out_full[resume_idx:]
                
                if transition_style == "Hard Beat Drop":
                    silence_len = int(0.15 * sr)
                    if y1_part.ndim == 2:
                        silence = np.zeros((2, silence_len), dtype=np.float32)
                        y_out = np.hstack((y1_part, silence, y2_part))
                        if return_to_track_1:
                            y_out = np.hstack((y_out, silence, track_1_part_2))
                    else:
                        silence = np.zeros(silence_len, dtype=np.float32)
                        y_out = np.concatenate([y1_part, silence, y2_part])
                        if return_to_track_1:
                            y_out = np.concatenate([y_out, silence, track_1_part_2])
                else:
                    # Smooth crossfade
                    if y1_part.ndim == 2:
                        y_out_l = _crossfade(y1_part[0], y2_part[0], sr, fade_seconds=crossfade_sec)
                        y_out_r = _crossfade(y1_part[1], y2_part[1], sr, fade_seconds=crossfade_sec)
                        y_out = np.vstack((y_out_l, y_out_r))
                        
                        if return_to_track_1:
                            y_out_l = _crossfade(y_out[0], track_1_part_2[0], sr, fade_seconds=crossfade_sec)
                            y_out_r = _crossfade(y_out[1], track_1_part_2[1], sr, fade_seconds=crossfade_sec)
                            y_out = np.vstack((y_out_l, y_out_r))
                    else:
                        y_out = _crossfade(y1_part, y2_part, sr, fade_seconds=crossfade_sec)
                        
                        if return_to_track_1:
                            y_out = _crossfade(y_out, track_1_part_2, sr, fade_seconds=crossfade_sec)

    # ── Step 8: Final fade & normalisation ────────────────────────
    if fade_flag:
        # Note: fade_in_out expects 1D, so if 8D made it 2D we must fade both channels
        if y_out.ndim == 2:
            y_out[0] = _fade_in_out(y_out[0], sr, fade_seconds=1.0)
            y_out[1] = _fade_in_out(y_out[1], sr, fade_seconds=1.0)
        else:
            y_out = _fade_in_out(y_out, sr, fade_seconds=1.0)

    max_val = np.max(np.abs(y_out)) + 1e-6
    y_out = y_out / max_val * 0.98
    
    # transpose to (samples, channels) for standard writing if stereo
    if y_out.ndim == 2:
        y_out = y_out.T
        
    return y_out, sr

# ---------- Presets ----------

def get_preset_params(preset_name: str):
    """
    Returns a dict with at least:
    - speed
    - pitch
    and optional suggested section params.
    """
    params = {
        "speed": 1.0,
        "pitch": 0,
        "bass1": 0.2, "high1": 0.2, "reverb1": 0.2, "lofi1": 0.0,
        "bass2": 0.7, "high2": 0.4, "reverb2": 0.3, "lofi2": 0.1,
        "bass3": 0.35, "high3": 0.2, "reverb3": 0.4, "lofi3": 0.4,
    }

    if preset_name == "Slowed Reverb":
        params["speed"] = 0.82
        params["pitch"] = -3

        params["bass1"] = 0.25
        params["high1"] = 0.15
        params["reverb1"] = 0.6
        params["lofi1"] = 0.3

        params["bass2"] = 0.7
        params["high2"] = 0.25
        params["reverb2"] = 0.8
        params["lofi2"] = 0.4

        params["bass3"] = 0.3
        params["high3"] = 0.15
        params["reverb3"] = 0.9
        params["lofi3"] = 0.5

    elif preset_name == "Lo-Fi Slow":
        params["speed"] = 0.8
        params["pitch"] = -2

    elif preset_name == "Nightcore":
        params["speed"] = 1.3
        params["pitch"] = 3

    elif preset_name == "Podcast Clean":
        params["speed"] = 1.0
        params["pitch"] = 0

    return params
