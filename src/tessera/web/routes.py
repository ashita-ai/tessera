"""Web UI routes for Tessera."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["web"])

# Template directory
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    """Dashboard page."""
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "active_page": "dashboard"},
    )


@router.get("/users", response_class=HTMLResponse)
async def users_list(request: Request) -> HTMLResponse:
    """Users list page."""
    return templates.TemplateResponse(
        "users.html",
        {"request": request, "active_page": "users"},
    )


@router.get("/users/{user_id}", response_class=HTMLResponse)
async def user_detail(request: Request, user_id: str) -> HTMLResponse:
    """User detail page."""
    return templates.TemplateResponse(
        "user_detail.html",
        {"request": request, "active_page": "users", "user_id": user_id},
    )


@router.get("/teams", response_class=HTMLResponse)
async def teams_list(request: Request) -> HTMLResponse:
    """Teams list page."""
    return templates.TemplateResponse(
        "teams.html",
        {"request": request, "active_page": "teams"},
    )


@router.get("/teams/{team_id}", response_class=HTMLResponse)
async def team_detail(request: Request, team_id: str) -> HTMLResponse:
    """Team detail page."""
    return templates.TemplateResponse(
        "team_detail.html",
        {"request": request, "active_page": "teams", "team_id": team_id},
    )


@router.get("/assets", response_class=HTMLResponse)
async def assets_list(request: Request) -> HTMLResponse:
    """Assets list page."""
    return templates.TemplateResponse(
        "assets.html",
        {"request": request, "active_page": "assets"},
    )


@router.get("/assets/{asset_id}", response_class=HTMLResponse)
async def asset_detail(request: Request, asset_id: str) -> HTMLResponse:
    """Asset detail page."""
    return templates.TemplateResponse(
        "asset_detail.html",
        {"request": request, "active_page": "assets", "asset_id": asset_id},
    )


@router.get("/contracts", response_class=HTMLResponse)
async def contracts_list(request: Request) -> HTMLResponse:
    """Contracts list page."""
    return templates.TemplateResponse(
        "contracts.html",
        {"request": request, "active_page": "contracts"},
    )


@router.get("/contracts/{contract_id}", response_class=HTMLResponse)
async def contract_detail(request: Request, contract_id: str) -> HTMLResponse:
    """Contract detail page."""
    return templates.TemplateResponse(
        "contract_detail.html",
        {"request": request, "active_page": "contracts", "contract_id": contract_id},
    )


@router.get("/proposals", response_class=HTMLResponse)
async def proposals_list(request: Request) -> HTMLResponse:
    """Proposals list page."""
    return templates.TemplateResponse(
        "proposals.html",
        {"request": request, "active_page": "proposals"},
    )


@router.get("/proposals/{proposal_id}", response_class=HTMLResponse)
async def proposal_detail(request: Request, proposal_id: str) -> HTMLResponse:
    """Proposal detail page."""
    return templates.TemplateResponse(
        "proposal_detail.html",
        {"request": request, "active_page": "proposals", "proposal_id": proposal_id},
    )
