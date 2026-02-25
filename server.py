import logging
import os
import subprocess
import sys
import asyncio
import threading
import json
import tempfile
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
import uvicorn

# os.environ["GOOGLE_API_KEY"] = ""
os.environ["GOOGLE_API_KEY"] = os.getenv("GOOGLE_API_KEY", "")

from dotenv import load_dotenv
load_dotenv(dotenv_path=".env.local")

_loop: asyncio.AbstractEventLoop | None = None

@asynccontextmanager
async def _lifespan(app: FastAPI):
    global _loop
    _loop = asyncio.get_running_loop()
    yield

app = FastAPI(title="Voice Chatbot API", lifespan=_lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("server")

agent_process: subprocess.Popen | None = None
log_buffer:      list[str]           = []
log_subscribers: list[asyncio.Queue] = []
tx_buffer:       list[dict]          = []
tx_subscribers:  list[asyncio.Queue] = []


def _fan_out(subscribers, payload):
    if not _loop or _loop.is_closed():
        return
    for q in list(subscribers):
        try:
            _loop.call_soon_threadsafe(q.put_nowait, payload)
        except Exception:
            pass


def _reader_thread(proc: subprocess.Popen):
    global log_buffer, tx_buffer
    for raw in iter(proc.stdout.readline, ""):
        line = raw.rstrip()
        if not line:
            continue
        log_buffer.append(line)
        if len(log_buffer) > 500:
            log_buffer = log_buffer[-500:]
        _fan_out(log_subscribers, line)

        if "TRANSCRIPT_USER:" in line:
            text = line.split("TRANSCRIPT_USER:", 1)[1].strip()
            if text:
                ev = {"type": "transcript", "role": "user", "text": text}
                tx_buffer.append(ev)
                _fan_out(tx_subscribers, ev)
        elif "TRANSCRIPT_AGENT:" in line:
            text = line.split("TRANSCRIPT_AGENT:", 1)[1].strip()
            if text:
                ev = {"type": "transcript", "role": "agent", "text": text}
                tx_buffer.append(ev)
                _fan_out(tx_subscribers, ev)
        elif "AGENT_STATE:" in line:
            state = line.split("AGENT_STATE:", 1)[1].strip()
            _fan_out(tx_subscribers, {"type": "state", "state": state})

    _fan_out(log_subscribers, None)
    _fan_out(tx_subscribers, {"type": "state", "state": "stopped"})


@app.get("/")
async def root():
    return FileResponse("index.html")

@app.get("/status")
async def get_status():
    if agent_process and agent_process.poll() is None:
        return {"status": "running"}
    return {"status": "stopped"}


class AgentConfig(BaseModel):
    instructions: str = ""
    voice: str = "Puck"
    model: str = "gemini-2.5-flash-native-audio-preview-12-2025"


def _build_agent_code(instructions, model, voice, api_key):
    I = json.dumps(instructions)
    M = json.dumps(model)
    V = json.dumps(voice)
    K = json.dumps(api_key)

    return f"""import logging, os, asyncio, sys
os.environ['GOOGLE_API_KEY'] = {K}
from dotenv import load_dotenv
load_dotenv(dotenv_path='.env.local')
from livekit.agents import (
    AutoSubscribe, JobContext, JobProcess,
    WorkerOptions, cli, AgentSession, Agent, RoomInputOptions,
)
from livekit.plugins import google, noise_cancellation, silero

logging.basicConfig(level=logging.INFO, stream=sys.stdout, force=True)
logger = logging.getLogger('voice-chatbot')

INSTRUCTIONS = {I}
MODEL = {M}
VOICE = {V}


def emit(line):
    print(line, flush=True)


class VoiceAssistant(Agent):
    def __init__(self):
        super().__init__(instructions=INSTRUCTIONS)

    async def on_enter(self):
        emit('AGENT_STATE: active')
        await self.session.generate_reply(
            instructions='Greet the user warmly and let them know you are ready to chat.'
        )

    async def on_user_turn_completed(self, turn_ctx, new_message):
        # Fallback: extract text from turn message items
        text = ''
        try:
            for item in new_message.items:
                if hasattr(item, 'text') and item.text:
                    text += item.text
        except Exception:
            pass
        if text.strip():
            emit('TRANSCRIPT_USER: ' + text.strip())
        emit('AGENT_STATE: active')
        await super().on_user_turn_completed(turn_ctx, new_message)


async def entrypoint(ctx: JobContext):
    logger.info('Connecting to room: ' + ctx.room.name)
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    session = AgentSession(
        llm=google.beta.realtime.RealtimeModel(
            model=MODEL,
            voice=VOICE,
            temperature=0.8,
        ),
        vad=ctx.proc.userdata['vad'],
        allow_interruptions=True,
    )

    @session.on('conversation_item_added')
    def on_item(ev):
        try:
            role = str(ev.item.role).lower()
            text = ''
            if hasattr(ev.item, 'text_content') and ev.item.text_content:
                text = ev.item.text_content
            elif hasattr(ev.item, 'content') and ev.item.content:
                for c in ev.item.content:
                    if hasattr(c, 'text') and c.text:
                        text += c.text
            text = text.strip()
            if not text:
                return
            if role == 'user':
                emit('TRANSCRIPT_USER: ' + text)
            elif role in ('assistant', 'agent'):
                emit('TRANSCRIPT_AGENT: ' + text)
        except Exception as ex:
            logger.warning('item event error: ' + str(ex))

    @session.on('user_input_transcribed')
    def on_user_stt(ev):
        try:
            if hasattr(ev, 'transcript') and ev.is_final and ev.transcript.strip():
                emit('TRANSCRIPT_USER: ' + ev.transcript.strip())
        except Exception:
            pass

    @session.on('agent_state_changed')
    def on_state(ev):
        try:
            s = str(ev.new_state).lower().split('.')[-1]
            emit('AGENT_STATE: ' + s)
        except Exception:
            pass

    await session.start(
        room=ctx.room,
        agent=VoiceAssistant(),
        room_input_options=RoomInputOptions(noise_cancellation=noise_cancellation.BVC()),
    )
    emit('AGENT_STATE: active')
    await asyncio.Event().wait()


def prewarm(proc: JobProcess):
    proc.userdata['vad'] = silero.VAD.load()


if __name__ == '__main__':
    cli.run_app(WorkerOptions(
        entrypoint_fnc=entrypoint,
        agent_name='voice-chatbot',
        prewarm_fnc=prewarm,
    ))
"""


@app.post("/start")
async def start_agent(config: AgentConfig):
    global agent_process, log_buffer, tx_buffer, log_subscribers, tx_subscribers

    if agent_process and agent_process.poll() is None:
        return {"message": "Agent already running", "status": "running"}

    log_buffer.clear()
    tx_buffer.clear()
    log_subscribers.clear()
    tx_subscribers.clear()

    instructions = config.instructions or (
        "You are a helpful and friendly AI voice assistant. "
        "Listen carefully to what the user says and respond naturally."
    )

    code = _build_agent_code(
        instructions=instructions,
        model=config.model,
        voice=config.voice,
        api_key=os.environ.get("GOOGLE_API_KEY", ""),
    )

    agent_file = os.path.join(tempfile.gettempdir(), "_agent_runtime.py")
    with open(agent_file, "w", encoding="utf-8") as f:
        f.write(code)

    agent_process = subprocess.Popen(
        [sys.executable, "-u", agent_file, "console"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    threading.Thread(target=_reader_thread, args=(agent_process,), daemon=True).start()
    logger.info(f"Agent started — PID {agent_process.pid}")
    return {"message": "Agent started", "status": "running", "pid": agent_process.pid}


@app.post("/stop")
async def stop_agent():
    global agent_process
    if agent_process and agent_process.poll() is None:
        agent_process.terminate()
        try:
            await asyncio.wait_for(asyncio.to_thread(agent_process.wait), timeout=6)
        except asyncio.TimeoutError:
            agent_process.kill()
        agent_process = None
        return {"message": "Agent stopped", "status": "stopped"}
    return {"message": "Agent was not running", "status": "stopped"}


@app.get("/logs/stream")
async def stream_logs():
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    log_subscribers.append(q)

    async def generate():
        for line in list(log_buffer):
            yield f"data: {line}\n\n"
        try:
            while True:
                try:
                    line = await asyncio.wait_for(q.get(), timeout=25)
                    if line is None:
                        yield "data: agent process exited\n\n"
                        break
                    yield f"data: {line}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            if q in log_subscribers:
                log_subscribers.remove(q)

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/events/stream")
async def stream_events():
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    tx_subscribers.append(q)

    async def generate():
        for ev in list(tx_buffer):
            yield f"data: {json.dumps(ev)}\n\n"
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=25)
                    yield f"data: {json.dumps(ev)}\n\n"
                    if ev.get("type") == "state" and ev.get("state") == "stopped":
                        break
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            if q in tx_subscribers:
                tx_subscribers.remove(q)

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)