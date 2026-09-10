from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yt_dlp
import os
import uuid

app = FastAPI(title="CK Cuts Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUT_DIR = "/tmp/ck-cuts"
os.makedirs(OUTPUT_DIR, exist_ok=True)


class CutRequest(BaseModel):
    youtube_url: str
    start_time: float
    end_time: float


@app.get("/")
def health():
    return {
        "status": "online",
        "service": "CK Cuts Backend"
    }


@app.post("/api/cuts/render")
def render_cut(request: CutRequest):

    if request.end_time <= request.start_time:
        raise HTTPException(
            status_code=400,
            detail="O tempo final deve ser maior que o inicial."
        )

    duration = request.end_time - request.start_time

    if duration > 180:
        raise HTTPException(
            status_code=400,
            detail="O corte não pode ultrapassar 3 minutos."
        )

    job_id = str(uuid.uuid4())
    output = os.path.join(OUTPUT_DIR, f"{job_id}.mp4")

    try:
        ydl_opts = {
            "format": "bestvideo+bestaudio/best",
            "outtmpl": output,
            "merge_output_format": "mp4",
            "download_ranges": yt_dlp.utils.download_range_func(
                None,
                [(request.start_time, request.end_time)]
            ),
            "force_keyframes_at_cuts": True,
            "noplaylist": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([request.youtube_url])

        if not os.path.exists(output):
            raise Exception("Arquivo de vídeo não foi criado.")

        return {
            "status": "completed",
            "job_id": job_id,
            "progress": 100,
            "output_file": output
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
