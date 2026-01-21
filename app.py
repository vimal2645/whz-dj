import streamlit as st
import soundfile as sf
import io

from bgm_core.remix import remix_audio


# ================== PAGE CONFIG ==================
st.set_page_config(page_title="WHZ LoopRoom", layout="wide")


# ================== CUSTOM CSS (COOL + CLEAR) ==================
CUSTOM_CSS = """
<style>
:root {
    --bg-dark: #020617;
    --bg-mid: #02081f;
    --accent-blue: #38bdf8;
    --accent-purple: #a855f7;
    --accent-green: #22c55e;
    --text-main: #e5e7eb;
    --text-muted: #9ca3af;
}

/* Background: smooth dark gradient with subtle noise-like feel */
[data-testid="stAppViewContainer"] {
    background: radial-gradient(circle at 0% 0%, #020617 0%, #02081f 40%, #020617 100%);
    color: var(--text-main);
}

/* Sidebar */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #020617, #020617);
    border-right: 1px solid #1f2937;
    color: var(--text-main);
}

/* Hide default Streamlit header/footer */
header[data-testid="stHeader"] {background: transparent;}
footer {visibility: hidden;}

/* Main card (glassmorphism, but dark and readable) */
.main-card {
    position: relative;
    background: linear-gradient(135deg, rgba(15,23,42,0.92), rgba(15,23,42,0.96));
    border-radius: 22px;
    padding: 1.7rem 2.1rem;
    border: 1px solid rgba(148, 163, 184, 0.3);
    box-shadow:
        0 24px 55px rgba(15, 23, 42, 0.9),
        0 0 0 1px rgba(15, 23, 42, 0.9);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    animation: cardFadeIn 0.4s ease-out;
}

/* Decorative glow behind card */
.main-card::before {
    content: "";
    position: absolute;
    inset: -1px;
    border-radius: inherit;
    background: radial-gradient(circle at top left, rgba(56,189,248,0.35), transparent 55%),
                radial-gradient(circle at bottom right, rgba(168,85,247,0.28), transparent 60%);
    opacity: 0.7;
    z-index: -1;
}

/* Title */
.app-title {
    font-size: 2.2rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-main);
}
.app-subtitle {
    font-size: 0.96rem;
    color: var(--text-muted);
}

/* Section title */
.section-title {
    font-size: 1.0rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.16em;
    color: var(--text-muted);
    margin-top: 0.4rem;
    margin-bottom: 0.35rem;
}

/* Labels and general text: high contrast */
label, .stText, .stMarkdown, .stNumberInput label, .stSlider label {
    color: var(--text-main) !important;
}

/* Buttons */
div.stButton > button:first-child {
    background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple));
    color: #020617;
    border-radius: 999px;
    padding: 0.55rem 1.7rem;
    font-weight: 700;
    border: none;
    box-shadow: 0 16px 36px rgba(56, 189, 248, 0.45);
    transition: all 0.16s ease-out;
}
div.stButton > button:first-child:hover {
    transform: translateY(-1px) scale(1.01);
    box-shadow: 0 20px 44px rgba(129, 140, 248, 0.7);
}

/* Sliders accent */
.stSlider > div > div > div {
    background: linear-gradient(90deg, var(--accent-blue), var(--accent-green)) !important;
}

/* Checkboxes text */
.stCheckbox > label {
    color: var(--text-main) !important;
}

/* Audio player tweaks (WebKit) */
audio::-webkit-media-controls-panel,
audio::-webkit-media-controls-enclosure {
    background-color: #020617;
}
audio::-webkit-media-controls-current-time-display,
audio::-webkit-media-controls-time-remaining-display {
    color: #e5e7eb;
}
audio::-webkit-media-controls-timeline {
    background-color: #111827;
    border-radius: 999px;
    margin-left: 10px;
    margin-right: 10px;
}
audio {
    width: 100%;
}

/* Small glowing pill */
.tag-pill {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.22rem 0.7rem;
    border-radius: 999px;
    background: rgba(15, 23, 42, 0.95);
    border: 1px solid rgba(56, 189, 248, 0.65);
    color: #bae6fd;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.14em;
}

/* Fade-in animation */
@keyframes cardFadeIn {
    from { opacity: 0; transform: translateY(6px);}
    to   { opacity: 1; transform: translateY(0);}
}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ================== HEADER ==================
st.markdown(
    """
<div class="main-card">
  <div class="app-title">WHZ LoopRoom</div>
  <div class="app-subtitle">
    Three‑section remix tool to turn any track into smooth background music with fine control.
  </div>
  <div style="margin-top:0.6rem;">
    <span class="tag-pill">🎧 Remix existing song</span>
  </div>
</div>
""",
    unsafe_allow_html=True,
)
st.write("")


# ================== REMIX EXISTING (ONLY MODE) ==================
st.markdown('<div class="main-card">', unsafe_allow_html=True)
st.markdown(
    '<div class="section-title">Remix controls</div>',
    unsafe_allow_html=True,
)

audio_file = st.file_uploader("Upload a song (mp3/wav)", type=["mp3", "wav"])

st.markdown("### Global Controls")
col_g1, col_g2 = st.columns(2)
with col_g1:
    speed = st.slider("Speed (0.3 = very slow, 2.0 = fast)", 0.3, 2.0, 1.0, 0.05)
    pitch = st.slider("Pitch shift (semitones)", -12, 12, 0, 1)
with col_g2:
    fade = st.checkbox("Fade in / fade out", value=True)
    reverse_flag = st.checkbox("Reverse whole track", value=False)

st.markdown("### Section Times (seconds)")
t1 = st.number_input("End of Section 1 (t1)", min_value=0.0, value=30.0, step=1.0)
t2 = st.number_input("End of Section 2 (t2)", min_value=0.0, value=60.0, step=1.0)

st.markdown("### Section 1 (Intro)")
c1_1, c1_2, c1_3, c1_4 = st.columns(4)
with c1_1:
    bass1 = st.slider("Bass 1", 0, 100, 20, key="bass1") / 100.0
with c1_2:
    high1 = st.slider("Highs 1", 0, 100, 20, key="high1") / 100.0
with c1_3:
    reverb1 = st.slider("Reverb 1", 0, 100, 20, key="reverb1") / 100.0
with c1_4:
    lofi1 = st.slider("Lo-fi 1", 0, 100, 0, key="lofi1") / 100.0

st.markdown("### Section 2 (Drop)")
c2_1, c2_2, c2_3, c2_4 = st.columns(4)
with c2_1:
    bass2 = st.slider("Bass 2", 0, 100, 60, key="bass2") / 100.0
with c2_2:
    high2 = st.slider("Highs 2", 0, 100, 40, key="high2") / 100.0
with c2_3:
    reverb2 = st.slider("Reverb 2", 0, 100, 30, key="reverb2") / 100.0
with c2_4:
    lofi2 = st.slider("Lo-fi 2", 0, 100, 10, key="lofi2") / 100.0

st.markdown("### Section 3 (Outro)")
c3_1, c3_2, c3_3, c3_4 = st.columns(4)
with c3_1:
    bass3 = st.slider("Bass 3", 0, 100, 35, key="bass3") / 100.0
with c3_2:
    high3 = st.slider("Highs 3", 0, 100, 20, key="high3") / 100.0
with c3_3:
    reverb3 = st.slider("Reverb 3", 0, 100, 40, key="reverb3") / 100.0
with c3_4:
    lofi3 = st.slider("Lo-fi 3", 0, 100, 40, key="lofi3") / 100.0

st.markdown("### Quick 15s Preview")
preview_start = st.number_input(
    "Preview start time (sec)", min_value=0.0, value=0.0, step=1.0
)

col_btn1, col_btn2 = st.columns(2)
with col_btn1:
    preview_click = st.button("▶ Preview 15s Segment")
with col_btn2:
    full_click = st.button("💾 Process Remix (Full Track)")

st.markdown("</div>", unsafe_allow_html=True)


# ================== PREVIEW LOGIC ==================
if audio_file is not None and preview_click:
    with st.spinner("Rendering 15s preview..."):
        y_prev, sr_prev = remix_audio(
            audio_file,
            speed=speed,
            pitch_steps=pitch,
            fade_flag=fade,
            reverse_flag=reverse_flag,
            t1=t1,
            t2=t2,
            bass1=bass1,
            high1=high1,
            reverb1=reverb1,
            lofi1=lofi1,
            bass2=bass2,
            high2=high2,
            reverb2=reverb2,
            lofi2=lofi2,
            bass3=bass3,
            high3=high3,
            reverb3=reverb3,
            lofi3=lofi3,
            start_time=preview_start,
            duration=15.0,
        )

    buf_prev = io.BytesIO()
    sf.write(buf_prev, y_prev, sr_prev, format="wav")
    buf_prev.seek(0)
    st.audio(buf_prev)  # st.audio accepts wav bytes/file-like [web:123]


# ================== FULL REMIX LOGIC ==================
if audio_file is not None and full_click:
    with st.spinner("Processing full remix..."):
        y_out, sr_out = remix_audio(
            audio_file,
            speed=speed,
            pitch_steps=pitch,
            fade_flag=fade,
            reverse_flag=reverse_flag,
            t1=t1,
            t2=t2,
            bass1=bass1,
            high1=high1,
            reverb1=reverb1,
            lofi1=lofi1,
            bass2=bass2,
            high2=high2,
            reverb2=reverb2,
            lofi2=lofi2,
            bass3=bass3,
            high3=high3,
            reverb3=reverb3,
            lofi3=lofi3,
            start_time=0.0,
            duration=None,
        )

    buf = io.BytesIO()
    sf.write(buf, y_out, sr_out, format="wav")
    buf.seek(0)
    st.audio(buf)
    st.download_button(
        "Download Remixed BGM",
        buf,
        file_name="remixed_bgm.wav",
        mime="audio/wav",
    )
