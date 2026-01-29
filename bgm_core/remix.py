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

# ---------- Section processor ----------

def _process_section(y, sr, bass_amount, high_amount, reverb_amount, lofi_amount):
    """
    One simple chain for all sections.
    """
    y = _reverb(y, sr, amount=reverb_amount)
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
):
    """
    DJ-style remix of existing audio with 3 timeline sections.
    - Global: speed, pitch, fade, reverse.
    - Per-section: bass/high/reverb/lofi.
    - If duration is not None, only [start_time, start_time+duration] is processed (for preview).
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

    # Clamp to musical ranges to keep quality
    speed = float(np.clip(speed, 0.6, 1.3))       # avoid extreme time-stretch artifacts [web:498]
    pitch_steps = int(np.clip(pitch_steps, -7, 7))

    # Global speed & pitch
    if speed != 1.0:
        y = librosa.effects.time_stretch(y, rate=speed)  # [web:493]
    if pitch_steps != 0:
        y = librosa.effects.pitch_shift(y, sr=sr, n_steps=pitch_steps)

    # Global reverse (before sectioning)
    if reverse_flag:
        y = _reverse_audio(y)

    n = len(y)
    if n == 0:
        return y, sr

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

    # Process each section
    if len(y1) > 0:
        y1 = _process_section(y1, sr, bass1, high1, reverb1, lofi1)
    if len(y2) > 0:
        y2 = _process_section(y2, sr, bass2, high2, reverb2, lofi2)
    if len(y3) > 0:
        y3 = _process_section(y3, sr, bass3, high3, reverb3, lofi3)

    if len(y2) or len(y3):
        y_out = np.concatenate([y1, y2, y3])
    else:
        y_out = y1

    # Global fade last
    if fade_flag:
        y_out = _fade_in_out(y_out, sr, fade_seconds=1.0)

    max_val = np.max(np.abs(y_out)) + 1e-6
    y_out = y_out / max_val * 0.98
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
