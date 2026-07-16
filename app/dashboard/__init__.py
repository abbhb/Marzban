import atexit
import os
import re
import subprocess
from pathlib import Path

from app import app
from config import DEBUG, VITE_BASE_API, DASHBOARD_PATH
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

base_dir = Path(__file__).parent
build_dir = base_dir / 'build'
statics_dir = build_dir / 'statics'

IMMUTABLE_CACHE_CONTROL = 'public, max-age=31536000, immutable'
HTML_CACHE_CONTROL = 'no-cache, max-age=0, must-revalidate'
REVALIDATE_CACHE_CONTROL = 'public, max-age=3600, must-revalidate'
DEFAULT_STATIC_CACHE_CONTROL = 'public, max-age=86400, must-revalidate'
HASHED_ASSET_RE = re.compile(r'\.[A-Za-z0-9_-]{8,}\.')


class DashboardStaticFiles(StaticFiles):
    """Serve dashboard files with cache rules that match Vite's filenames."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        content_type = response.headers.get('content-type', '').lower()
        normalized_path = path.replace('\\', '/')
        filename = normalized_path.rsplit('/', 1)[-1]
        is_html_path = (
            normalized_path in {'', '.', 'index.html', '404.html'}
            or normalized_path.endswith('.html')
        )

        if is_html_path or content_type.startswith('text/html'):
            cache_control = HTML_CACHE_CONTROL
        elif HASHED_ASSET_RE.search(filename):
            cache_control = IMMUTABLE_CACHE_CONTROL
        elif normalized_path.startswith('locales/') and normalized_path.endswith('.json'):
            cache_control = REVALIDATE_CACHE_CONTROL
        else:
            cache_control = DEFAULT_STATIC_CACHE_CONTROL

        response.headers['Cache-Control'] = cache_control
        return response


def build():
    proc = subprocess.Popen(
        ['npm', 'run', 'build', '--',  '--outDir', build_dir, '--assetsDir', 'statics'],
        env={**os.environ, 'VITE_BASE_API': VITE_BASE_API},
        cwd=base_dir
    )
    proc.wait()
    with open(build_dir / 'index.html', 'r') as file:
        html = file.read()
    with open(build_dir / '404.html', 'w') as file:
        file.write(html)


def run_dev():
    proc = subprocess.Popen(
        ['npm', 'run', 'dev', '--', '--host', '0.0.0.0', '--clearScreen', 'false', '--base', os.path.join(DASHBOARD_PATH, '')],
        env={**os.environ, 'VITE_BASE_API': VITE_BASE_API},
        cwd=base_dir
    )

    atexit.register(proc.terminate)


def run_build():
    if not build_dir.is_dir():
        build()

    app.mount(
        DASHBOARD_PATH,
        DashboardStaticFiles(directory=build_dir, html=True),
        name="dashboard"
    )
    app.mount(
        '/statics/',
        DashboardStaticFiles(directory=statics_dir, html=True),
        name="statics"
    )


@app.on_event("startup")
def startup():
    if DEBUG:
        run_dev()
    else:
        run_build()
