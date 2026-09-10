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
    Cria temporariamente um cookies.txt usando
    a variável YOUTUBE_COOKIES do Railway.
    """

    cookies = os.getenv("YOUTUBE_COOKIES")

    if not cookies:
        return None

    cookie_file = os.path.join(
        tempfile.gettempdir(),
        "youtube_cookies.txt"
    )

    with open(
        cookie_file,
        "w",
        encoding="utf-8",
        newline="\n"
    ) as f:
        f.write(cookies)

    return cookie_file


@app.post("/api/cuts/render")
def render_cut(request: CutRequest):

    # ---------------------------------------------------------
    # VALIDAÇÕES
    # ---------------------------------------------------------

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

    if duration <= 0:
        raise HTTPException(
            status_code=400,
            detail="Duração inválida."
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

        # -----------------------------------------------------
        # COOKIES
        # -----------------------------------------------------

        cookie_file = create_cookie_file()

        # -----------------------------------------------------
        # YT-DLP
        # -----------------------------------------------------

        ydl_opts = {

            # Tenta primeiro até 1080p.
            # Se não existir, cai para qualquer
            # combinação disponível.
            "format": (
                "bestvideo[height<=1080]+bestaudio/"
                "bestvideo+bestaudio/"
                "best"
            ),

            "outtmpl": source_template,

            "merge_output_format": "mp4",

            # Baixa somente o intervalo solicitado
            "download_ranges": yt_dlp.utils.download_range_func(
                None,
                [
                    (
                        request.start_time,
                        request.end_time
                    )
                ]
            ),

            "force_keyframes_at_cuts": True,

            "noplaylist": True,

            # Reduz consumo de memória
            "concurrent_fragment_downloads": 1,

            # Runtime JavaScript
            "js_runtimes": {
                "node": {}
            },

            # Permite ao yt-dlp obter os componentes EJS
            "remote_components": [
                "ejs:github"
            ],

            # Cookies
            "cookiefile": cookie_file,

            # User-Agent
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/140.0.0.0 Safari/537.36"
                )
            },

            "quiet": False,

            "no_warnings": False,
        }

        # Se não houver cookie, remove a opção
        if not cookie_file:
            ydl_opts.pop("cookiefile", None)

        # -----------------------------------------------------
        # DOWNLOAD
        # -----------------------------------------------------

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([request.youtube_url])

        # -----------------------------------------------------
        # ENCONTRA O ARQUIVO BAIXADO
        # -----------------------------------------------------

        for file in os.listdir(OUTPUT_DIR):

            if file.startswith(
                job_id + "_source"
            ):

                candidate = os.path.join(
                    OUTPUT_DIR,
                    file
                )

                if os.path.isfile(candidate):
                    source_file = candidate
                    break

        if not source_file:

            raise Exception(
                "O arquivo de origem não foi encontrado "
                "após o download."
            )

        # -----------------------------------------------------
        # FFMPEG
        # -----------------------------------------------------

        log_path = os.path.join(
            OUTPUT_DIR,
            f"{job_id}.log"
        )

        command = [

            "ffmpeg",
            "-y",

            "-i",
            source_file,

            # Vertical 9:16
            "-vf",
            (
                "scale=1080:1920:"
                "force_original_aspect_ratio=increase,"
                "crop=1080:1920"
            ),

            # H264
            "-c:v",
            "libx264",

            # Velocidade
            "-preset",
            "veryfast",

            # Qualidade
            "-crf",
            "26",

            # Áudio
            "-c:a",
            "aac",

            "-b:a",
            "128k",

            "-movflags",
            "+faststart",

            output
        ]

        # Não acumula o log na RAM
        with open(
            log_path,
            "w"
        ) as log_file:

            subprocess.run(
                command,
                check=True,
                stdout=log_file,
                stderr=log_file
            )

        # -----------------------------------------------------
        # VERIFICA RESULTADO
        # -----------------------------------------------------

        if not os.path.exists(output):

            raise Exception(
                "O FFmpeg terminou, mas o arquivo final "
                "não foi criado."
            )

        # -----------------------------------------------------
        # LIMPEZA
        # -----------------------------------------------------

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
            detail=(
                "Erro ao baixar o vídeo do YouTube: "
                f"{str(e)}"
            )
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
