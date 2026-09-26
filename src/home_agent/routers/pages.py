from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="pages/index.html")


@router.get("/agents/home-diagnostics", response_class=HTMLResponse)
def home_diagnostics(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="pages/chat.html")
