from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yt_dlp
import os
import uuid
import tempfile
import glob

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


@app.post("/api/cuts/download")
def download_cut(request: CutRequest):

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

    if duration < 1:
        raise HTTPException(
            status_code=400,
            detail="O corte precisa ter pelo menos 1 segundo."
        )

    job_id = str(uuid.uuid4())

    output_template = os.path.join(
        OUTPUT_DIR,
        f"{job_id}.%(ext)s"
    )

    cookie_file = create_cookie_file()

    try:

        ydl_opts = {
            # Melhor qualidade disponível até 1080p.
            # Sem reencode.
            "format": (
                "bestvideo[height<=1080]+bestaudio/"
                "best[height<=1080]/"
                "best"
            ),

            "outtmpl": output_template,

            "merge_output_format": "mp4",

            # Baixa somente o intervalo escolhido
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

            # Reduz consumo do servidor
            "concurrent_fragment_downloads": 1,

            # YouTube / EJS
            "js_runtimes": {
                "node": {}
            },

            "remote_components": [
                "ejs:github"
            ],

            # Cookies
            "cookiefile": cookie_file,

            # Navegador
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

        if not cookie_file:
            ydl_opts.pop("cookiefile", None)

        # -----------------------------------------------
        # DOWNLOAD
        # -----------------------------------------------

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([request.youtube_url])

        # -----------------------------------------------
        # LOCALIZA ARQUIVO
        # -----------------------------------------------

        files = glob.glob(
            os.path.join(
                OUTPUT_DIR,
                f"{job_id}.*"
            )
        )

        files = [
            f for f in files
            if not f.endswith(".log")
        ]

        if not files:
            raise Exception(
                "O vídeo não foi encontrado após o download."
            )

        output_file = files[0]

        # -----------------------------------------------
        # LIMPA COOKIE TEMPORÁRIO
        # -----------------------------------------------

        if cookie_file and os.path.exists(cookie_file):
            os.remove(cookie_file)

        # -----------------------------------------------
        # RETORNA ARQUIVO
        # -----------------------------------------------

        return FileResponse(
            output_file,
            media_type="video/mp4",
            filename=f"ck-cuts-{job_id}.mp4"
        )

    except yt_dlp.utils.DownloadError as e:

        if cookie_file and os.path.exists(cookie_file):
            os.remove(cookie_file)

        raise HTTPException(
            status_code=500,
            detail=f"Erro ao baixar o vídeo do YouTube: {str(e)}"
        )

    except Exception as e:

        if cookie_file and os.path.exists(cookie_file):
            os.remove(cookie_file)

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
