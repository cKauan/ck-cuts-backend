from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yt_dlp
import os
import uuid
import subprocess
import tempfile

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


def create_cookie_file():
    cookies = os.getenv("YOUTUBE_COOKIES")

    if not cookies:
        return None

    path = os.path.join(
        tempfile.gettempdir(),
        "youtube_cookies.txt"
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write(cookies)

    return path


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

    source_template = os.path.join(
        OUTPUT_DIR,
        f"{job_id}_source.%(ext)s"
    )

    output = os.path.join(
        OUTPUT_DIR,
        f"{job_id}.mp4"
    )

    cookie_file = None
    source_file = None

    try:

        # --------------------------------------------------
        # COOKIES
        # --------------------------------------------------

        cookie_file = create_cookie_file()

        # --------------------------------------------------
        # DOWNLOAD
        # --------------------------------------------------

        ydl_opts = {
            # Limita o download para reduzir RAM
            "format": (
                "bestvideo[height<=720]+bestaudio/"
                "best[height<=720]/"
                "best"
            ),

            "outtmpl": source_template,

            "merge_output_format": "mp4",

            "download_ranges": yt_dlp.utils.download_range_func(
                None,
                [
                    (
                        request.start_time,
                        request.end_time
                    )
                ]
            ),

            "noplaylist": True,

            # Apenas uma parte por vez
            "concurrent_fragment_downloads": 1,

            # JS runtime
            "js_runtimes": {
                "node": {}
            },

            "remote_components": [
                "ejs:github"
            ],

            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/140.0.0.0 Safari/537.36"
                )
            },

            "quiet": False,
        }

        if cookie_file:
            ydl_opts["cookiefile"] = cookie_file

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([request.youtube_url])

        # --------------------------------------------------
        # LOCALIZA SOURCE
        # --------------------------------------------------

        for filename in os.listdir(OUTPUT_DIR):

            if filename.startswith(
                job_id + "_source"
            ):

                candidate = os.path.join(
                    OUTPUT_DIR,
                    filename
                )

                if os.path.isfile(candidate):
                    source_file = candidate
                    break

        if not source_file:
            raise Exception(
                "Arquivo de origem não encontrado."
            )

        # --------------------------------------------------
        # FFMPEG
        # --------------------------------------------------

        command = [
            "ffmpeg",
            "-y",

            "-threads",
            "1",

            "-i",
            source_file,

            # Vertical 9:16
            "-vf",
            (
                "scale=1080:1920:"
                "force_original_aspect_ratio=increase,"
                "crop=1080:1920"
            ),

            "-c:v",
            "libx264",

            # Extremamente rápido
            "-preset",
            "ultrafast",

            # Menor esforço de processamento
            "-crf",
            "28",

            "-c:a",
            "aac",

            "-b:a",
            "128k",

            "-movflags",
            "+faststart",

            output
        ]

        log_path = os.path.join(
            OUTPUT_DIR,
            f"{job_id}.log"
        )

        with open(log_path, "w") as log:

            subprocess.run(
                command,
                check=True,
                stdout=log,
                stderr=log
            )

        if not os.path.exists(output):
            raise Exception(
                "Arquivo final não foi criado."
            )

        # --------------------------------------------------
        # LIMPEZA
        # --------------------------------------------------

        if source_file and os.path.exists(source_file):
            os.remove(source_file)

        if cookie_file and os.path.exists(cookie_file):
            os.remove(cookie_file)

        return {
            "status": "completed",
            "job_id": job_id,
            "progress": 100,
            "output_file": output
        }

    except yt_dlp.utils.DownloadError as e:

        if cookie_file and os.path.exists(cookie_file):
            os.remove(cookie_file)

        raise HTTPException(
            status_code=500,
            detail=f"Erro ao baixar o vídeo do YouTube: {str(e)}"
        )

    except subprocess.CalledProcessError:

        if cookie_file and os.path.exists(cookie_file):
            os.remove(cookie_file)

        raise HTTPException(
            status_code=500,
            detail="FFmpeg falhou durante o processamento."
        )

    except Exception as e:

        if cookie_file and os.path.exists(cookie_file):
            os.remove(cookie_file)

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
