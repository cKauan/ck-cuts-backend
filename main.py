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
    """
    Cria temporariamente um cookies.txt a partir da variável
    YOUTUBE_COOKIES configurada no Railway.
    """

    cookies = os.getenv("YOUTUBE_COOKIES")

    if not cookies:
        return None

    cookie_file = os.path.join(
        tempfile.gettempdir(),
        "youtube_cookies.txt"
    )

    with open(cookie_file, "w", encoding="utf-8", newline="\n") as f:
        f.write(cookies)

    return cookie_file


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

        # ---------------------------------------------------------
        # COOKIES
        # ---------------------------------------------------------

        cookie_file = create_cookie_file()

        # ---------------------------------------------------------
        # DOWNLOAD DO TRECHO DO YOUTUBE
        # ---------------------------------------------------------

        ydl_opts = {
            # Limita a 1080p para reduzir consumo de memória
            "format": (
            "bestvideo[height<=1080]+bestaudio/"
            "bestvideo+bestaudio/"
            "best"
            ),

            "outtmpl": source_template,

            "merge_output_format": "mp4",

            "download_ranges": yt_dlp.utils.download_range_func(
                None,
                [(request.start_time, request.end_time)]
            ),

            "force_keyframes_at_cuts": True,

            "noplaylist": True,

            # Reduz consumo de RAM
            "concurrent_fragment_downloads": 1,

            # Evita mensagens desnecessárias
            "quiet": True,

            "no_warnings": True,

            # User-Agent semelhante a navegador
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/140.0.0.0 Safari/537.36"
                )
            },
        }

        # Só adiciona cookies se YOUTUBE_COOKIES existir
        if cookie_file:
            ydl_opts["cookiefile"] = cookie_file

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([request.youtube_url])

        # ---------------------------------------------------------
        # LOCALIZA O ARQUIVO BAIXADO
        # ---------------------------------------------------------

        for file in os.listdir(OUTPUT_DIR):

            if file.startswith(job_id + "_source"):

                candidate = os.path.join(
                    OUTPUT_DIR,
                    file
                )

                if os.path.isfile(candidate):
                    source_file = candidate
                    break

        if not source_file:
            raise Exception(
                "O arquivo de origem não foi encontrado após o download."
            )

        # ---------------------------------------------------------
        # FFMPEG
        # ---------------------------------------------------------

        command = [
            "ffmpeg",
            "-y",

            "-i",
            source_file,

            # Formato vertical 9:16
            "-vf",
            (
                "scale=1080:1920:"
                "force_original_aspect_ratio=increase,"
                "crop=1080:1920"
            ),

            # H.264
            "-c:v",
            "libx264",

            # Mais rápido / menor consumo
            "-preset",
            "veryfast",

            # Qualidade razoável para TikTok
            "-crf",
            "26",

            # Áudio
            "-c:a",
            "aac",

            "-b:a",
            "128k",

            # Otimiza MP4 para reprodução
            "-movflags",
            "+faststart",

            output
        ]

        # Não guardar todo o log do FFmpeg na memória
        with open(
            os.path.join(
                OUTPUT_DIR,
                f"{job_id}.log"
            ),
            "w"
        ) as log_file:

            subprocess.run(
                command,
                check=True,
                stdout=log_file,
                stderr=log_file
            )

        # ---------------------------------------------------------
        # VERIFICA SAÍDA
        # ---------------------------------------------------------

        if not os.path.exists(output):
            raise Exception(
                "O FFmpeg terminou, mas o arquivo final não foi criado."
            )

        # ---------------------------------------------------------
        # LIMPEZA
        # ---------------------------------------------------------

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
