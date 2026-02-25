# 🎙️ Gemini Voice AI

A real-time voice chatbot powered by **Google Gemini** and **LiveKit**, with a beautiful dark web UI showing live transcripts, agent state, and microphone waveforms.

---

## ✨ Features

- 🎤 **Real-time voice conversation** using Gemini 2.5 Flash native audio
- 📝 **Live transcript** — both user and agent messages appear as chat bubbles
- 🌊 **Microphone waveform** — visualizer reacts to your actual voice
- 🔄 **Agent state display** — shows Listening / Speaking / Thinking in real time
- 🔇 **Background noise cancellation** via LiveKit BVC
- ⚙️ **Configurable** — change system prompt, voice, and model from the UI
- 📡 **Server-Sent Events** for zero-latency log and transcript streaming


---

## 📋 Prerequisites

- Python 3.10+
- A [Google AI Studio](https://aistudio.google.com/app/apikey) API key (Gemini)
- A [LiveKit Cloud](https://cloud.livekit.io) account (free tier works)

---

## 🚀 Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/gemini-voice-ai.git
cd gemini-voice-ai
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

Create a `.env.local` file in the project root:

```env
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=APIxxxxxxxxxxxxxxxxx
LIVEKIT_API_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### 4. Add your Google API key

Open `server.py` and set your key:

```python
os.environ["GOOGLE_API_KEY"] = "your_google_api_key_here"
```

> ⚠️ Never commit your API key to GitHub. Use `.env.local` (already gitignored) instead.

### 5. Run the server

```bash
python server.py
```

### 6. Open the UI

Open  **index.html** in your browser.

### 7. Connect and talk

1. Click **▶ Start** in the UI
2. Open [LiveKit Agents Playground](https://agents-playground.livekit.io/)
3. Enter your LiveKit URL and credentials → click **Connect**
4. Start speaking — responses appear as chat bubbles in real time

---

## 📁 Project Structure

```
gemini-voice-ai/
├── server.py        # FastAPI backend — manages agent subprocess + SSE streams
├── index.html       # Frontend UI — visualizer, transcript, console
├── requirements.txt # Python dependencies
├── .env.local       # Your secrets (gitignored)
└── .gitignore
```

---

## ⚙️ Configuration

All settings are available in the UI sidebar:

| Setting | Description | Default |
|---|---|---|
| System Prompt | Instructions that define the agent's personality | Friendly assistant |
| Voice | Gemini voice character | Puck |
| Model | Gemini model to use | gemini-2.5-flash |

### Available voices

| Voice | Character |
|---|---|
| Puck | Energetic |
| Charon | Deep |
| Kore | Warm |
| Fenrir | Bold |
| Aoede | Melodic |

---

## 🏗️ Architecture

```
Browser (index.html)
    │
    ├── POST /start      → Spawns agent subprocess
    ├── GET  /logs/stream → Raw console logs (SSE)
    └── GET  /events/stream → Transcript + state events (SSE)

server.py (FastAPI)
    │
    └── _agent_runtime.py (LiveKit Agent subprocess)
            │
            ├── Google Gemini Realtime API (audio in/out)
            ├── Silero VAD (voice activity detection)
            └── LiveKit BVC (noise cancellation)
```

The agent subprocess prints structured markers (`TRANSCRIPT_USER:`, `TRANSCRIPT_AGENT:`, `AGENT_STATE:`) to stdout. The server parses these and fans them out to all SSE subscribers in real time.

---

## 🛠️ Troubleshooting

| Error | Fix |
|---|---|
| `GOOGLE_API_KEY reported as leaked` | Generate a new key at [Google AI Studio](https://aistudio.google.com/app/apikey) |
| `Agent already running` | Click **Stop** first, then **Start** again |
| Messages not appearing | Check console panel — look for `TRANSCRIPT_USER` / `TRANSCRIPT_AGENT` lines |
| Server restarting on its own | Make sure you run `python server.py` not `uvicorn server:app --reload` |
| `max_concurrent_jobs` error | Upgrade: `pip install --upgrade livekit-agents` |

---

## 📦 Dependencies

| Package | Purpose |
|---|---|
| `fastapi` | Web server + REST API |
| `uvicorn` | ASGI server |
| `livekit-agents` | LiveKit agent framework |
| `livekit-plugins-google` | Gemini Realtime model |
| `livekit-plugins-silero` | Voice activity detection |
| `livekit-plugins-noise-cancellation` | Background noise removal |
| `python-dotenv` | Load `.env.local` credentials |

---

## 📄 License

MIT License — feel free to use and modify.