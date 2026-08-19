# 🎵 Audio DSP Engine & REST API — Pitch, Time & Reverb Processing

> FastAPI REST API automating audio DSP operations — **pitch-shifting**, **time-stretching**, and **reverb** for custom audio tracks. Streamlit UI with NumPy PCM buffer processing. Tested via Swagger.

![FastAPI](https://img.shields.io/badge/FastAPI-REST_API-009688?logo=fastapi) ![Python](https://img.shields.io/badge/Python-3.10-blue?logo=python) ![Librosa](https://img.shields.io/badge/Librosa-Audio_DSP-purple) ![Streamlit](https://img.shields.io/badge/Streamlit-UI-FF4B4B?logo=streamlit) ![NumPy](https://img.shields.io/badge/NumPy-PCM-013243?logo=numpy)

## 🎯 What It Does
A DJ/audio production tool that:
1. **Accepts** audio files via REST API or Streamlit UI
2. **Processes** using DSP operations (pitch shift, time stretch, reverb)
3. **Returns** the transformed audio file
4. **Documents** all endpoints via Swagger UI

## 🎛️ DSP Operations
| Operation | Description | Parameter |
|-----------|-------------|-----------|
| Pitch Shift | Shift pitch up/down in semitones | `semitones: float` |
| Time Stretch | Speed up/slow down without pitch change | `rate: float` |
| Reverb | Add reverb/room effect | `room_size: float` |
| Normalize | Normalize audio volume | — |

## 📁 Structure
```
dj-audio-streaming-app/
├── main.py / app.py        # FastAPI application
├── dsp/
│   ├── pitch.py            # Pitch shifting (Librosa)
│   ├── stretch.py          # Time stretching
│   └── reverb.py           # Reverb processing
├── streamlit_app.py        # Streamlit UI
└── requirements.txt
```

## ⚙️ Setup & Run

### API Server
```bash
pip install -r requirements.txt
uvicorn main:app --reload
# Swagger UI: http://localhost:8000/docs
```

### Streamlit UI
```bash
streamlit run streamlit_app.py
```

## 🌐 API Endpoints
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/audio/pitch` | Pitch shift audio |
| POST | `/audio/stretch` | Time stretch audio |
| POST | `/audio/reverb` | Add reverb |
| POST | `/audio/process` | Apply multiple effects |
| GET | `/docs` | Swagger documentation |

## 🛠️ Tech Stack
`FastAPI` `Python` `Librosa` `NumPy` `SciPy` `Streamlit` `Swagger`

## 📜 On Resume (FSR)
> *"Built a FastAPI REST API automating pitch-shifting, time-stretching, and reverb for custom audio tracks, tested via Swagger."*

---
[LinkedIn](https://linkedin.com/in/vimalprakash26) | [GitHub](https://github.com/vimal2645)
