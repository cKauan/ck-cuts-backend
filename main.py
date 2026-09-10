from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yt_dlp
import os
import uuid
import subprocess

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

    source = os.path.join(OUTPUT_DIR, f"{job_id}_source.%(ext)s")
    output = os.path.join(OUTPUT_DIR, f"{job_id}.mp4")

    try:

        # Baixa no máximo 1080p para evitar estouro de memória
        ydl_opts = {
            "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
            "outtmpl": source,
            "merge_output_format": "mp4",
            "download_ranges": yt_dlp.utils.download_range_func(
                None,
                [(request.start_time, request.end_time)]
            ),
            "force_keyframes_at_cuts": True,
            "noplaylist": True,
            "concurrent_fragment_downloads": 1,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([request.youtube_url])

        # Localiza o arquivo baixado
        source_file = None

        for file in os.listdir(OUTPUT_DIR):
            if file.startswith(job_id + "_source"):
                source_file = os.path.join(OUTPUT_DIR, file)
                break

        if not source_file or not os.path.exists(source_file):
            raise Exception("Arquivo de origem não encontrado.")

        # Conversão para TikTok 9:16
        command = [
            "ffmpeg",
            "-y",
            "-i",
            source_file,
            "-vf",
            "scale=1080:1920:force_original_aspect_ratio=decrease,"
            "pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "26",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            output
        ]

        subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        os.remove(source_file)

        return {
            "status": "completed",
            "job_id": job_id,
            "progress": 100,
            "output_file": output
        }

    except subprocess.CalledProcessError as e:

        raise HTTPException(
            status_code=500,
            detail="FFmpeg falhou durante o processamento."
        )

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
