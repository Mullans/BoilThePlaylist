import json
import os
import secrets
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import httpx
from boiltheplaylist.llm import LLMResult, build_prompt, get_llm_client
from boiltheplaylist.spotify import (
    SpotifyClient,
    build_auth_url,
    exchange_code_for_token,
    refresh_token,
    token_is_expired,
)

BASE_DIR = Path(__file__).resolve().parent
PROMPT_PATH = BASE_DIR.parent / "data" / "boil_prompt.md"

SESSION_SECRET = os.getenv("SESSION_SECRET")
if not SESSION_SECRET:
    raise RuntimeError(
        "SESSION_SECRET environment variable must be set for session security."
    )

app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site="lax",
    https_only=False,
)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _get_redirect_uri(request: Request) -> str:
    configured = os.getenv("SPOTIFY_REDIRECT_URI")
    if configured:
        return configured
    fallback_url = request.url_for("spotify_callback")
    secure_url = fallback_url.replace(scheme="https")
    return str(secure_url)


def _require_spotify_token(request: Request) -> dict[str, Any]:
    token = request.session.get("spotify_token")
    if not token:
        raise HTTPException(status_code=401, detail="Spotify not connected")
    return token


async def _get_spotify_client(request: Request) -> SpotifyClient:
    token = _require_spotify_token(request)
    if token_is_expired(token):
        refreshed = await refresh_token(token.get("refresh_token"))
        request.session["spotify_token"] = refreshed
        token = refreshed
    return SpotifyClient(access_token=token["access_token"])


def _simplify_track(item: dict[str, Any]) -> dict[str, Any]:
    artists = ", ".join(artist["name"] for artist in item.get("artists", []))
    images = item.get("album", {}).get("images", [])
    image_url = images[0]["url"] if images else ""
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "artist": artists,
        "uri": item.get("uri"),
        "image": image_url,
        "preview_url": item.get("preview_url"),
    }


async def _resolve_sequence(
    spotify: SpotifyClient, sequence: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    resolved = []
    for item in sequence:
        title = item.get("title", "").strip()
        artist = item.get("artist", "").strip()
        spotify_item = None
        if title and artist:
            query = f"track:{title} artist:{artist}"
            matches = await spotify.search_tracks(query, limit=1)
            spotify_item = _simplify_track(matches[0]) if matches else None
        resolved.append(
            {
                "title": title,
                "artist": artist,
                "why": item.get("why", ""),
                "transition": item.get("transition", ""),
                "tags": item.get("tags", []),
                "spotify": spotify_item,
                "resolved": bool(spotify_item),
            }
        )
    return resolved


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/config")
async def config() -> JSONResponse:
    return JSONResponse(
        {
            "spotify_client_id": os.getenv("SPOTIFY_CLIENT_ID", ""),
            "spotify_redirect_uri": os.getenv("SPOTIFY_REDIRECT_URI", ""),
        }
    )


@app.get("/login")
async def login(request: Request) -> RedirectResponse:
    scope = os.getenv(
        "SPOTIFY_SCOPES",
        "playlist-modify-private playlist-modify-public user-read-email",
    )
    state = secrets.token_urlsafe(12)
    request.session["oauth_state"] = state
    redirect_uri = _get_redirect_uri(request)
    url = build_auth_url(redirect_uri=redirect_uri, state=state, scope=scope)
    return RedirectResponse(url)


@app.post("/logout")
async def logout(request: Request) -> JSONResponse:
    request.session.pop("spotify_token", None)
    request.session.pop("oauth_state", None)
    return JSONResponse({"connected": False})


@app.get("/callback", name="spotify_callback")
async def spotify_callback(request: Request) -> RedirectResponse:
    params = request.query_params
    code = params.get("code")
    state = params.get("state")
    error = params.get("error")

    if error:
        return RedirectResponse(f"/?error={error}")
    if not code:
        return RedirectResponse("/?error=missing_code")
    if state != request.session.get("oauth_state"):
        return RedirectResponse("/?error=state_mismatch")

    redirect_uri = _get_redirect_uri(request)
    token = await exchange_code_for_token(code=code, redirect_uri=redirect_uri)
    request.session["spotify_token"] = token

    return RedirectResponse("/?connected=1")


@app.get("/api/me")
async def me(request: Request) -> JSONResponse:
    token = request.session.get("spotify_token")
    if not token:
        return JSONResponse({"connected": False})
    spotify = await _get_spotify_client(request)
    profile = await spotify.get_profile()
    return JSONResponse(
        {
            "connected": True,
            "id": profile.get("id"),
            "display_name": profile.get("display_name"),
        }
    )


@app.post("/api/search")
async def search_tracks(
    request: Request, payload: dict[str, Any] = Body(...)
) -> JSONResponse:
    query = (payload.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query is required")

    spotify = await _get_spotify_client(request)
    results = await spotify.search_tracks(query)
    return JSONResponse({"results": [_simplify_track(item) for item in results]})


@app.post("/api/generate")
async def generate_playlist(
    request: Request, payload: dict[str, Any] = Body(...)
) -> JSONResponse:
    start = payload.get("start") or {}
    end = payload.get("end") or {}
    count = int(payload.get("count") or 0)
    constraints = payload.get("constraints") or {}

    if not start.get("name") or not start.get("artist"):
        raise HTTPException(status_code=400, detail="Start track is required")
    if not end.get("name") or not end.get("artist"):
        raise HTTPException(status_code=400, detail="End track is required")
    if count < 1 or count > 30:
        raise HTTPException(status_code=400, detail="Count must be 1-30")

    prompt = _load_prompt()
    prompt_preview = build_prompt(
        prompt,
        start["name"],
        start["artist"],
        end["name"],
        end["artist"],
        count,
        constraints,
    )
    llm = get_llm_client()
    llm_result: LLMResult = await llm.generate_playlist(
        prompt=prompt,
        start_title=start["name"],
        start_artist=start["artist"],
        end_title=end["name"],
        end_artist=end["artist"],
        count=count,
        constraints=constraints,
    )

    sequence = llm_result.sequence or []
    if not sequence:
        sequence = [
            {"title": start["name"], "artist": start["artist"]},
            {"title": end["name"], "artist": end["artist"]},
        ]
    if len(sequence) >= 1:
        sequence[0]["title"] = start["name"]
        sequence[0]["artist"] = start["artist"]
    if len(sequence) >= 2:
        sequence[-1]["title"] = end["name"]
        sequence[-1]["artist"] = end["artist"]

    llm_count = len(sequence)

    return JSONResponse(
        {
            "sequence": sequence,
            "llm_count": llm_count,
            "arc_summary": llm_result.arc_summary,
            "playlist_title": llm_result.playlist_title,
            "raw": llm_result.raw_text,
            "prompt": prompt_preview,
        }
    )


@app.post("/api/generate-stream")
async def generate_stream(
    request: Request, payload: dict[str, Any] = Body(...)
) -> StreamingResponse:
    start = payload.get("start") or {}
    end = payload.get("end") or {}
    count = int(payload.get("count") or 0)
    constraints = payload.get("constraints") or {}

    if not start.get("name") or not start.get("artist"):
        raise HTTPException(status_code=400, detail="Start track is required")
    if not end.get("name") or not end.get("artist"):
        raise HTTPException(status_code=400, detail="End track is required")
    if count < 1 or count > 30:
        raise HTTPException(status_code=400, detail="Count must be 1-30")

    prompt = _load_prompt()
    prompt_preview = build_prompt(
        prompt,
        start["name"],
        start["artist"],
        end["name"],
        end["artist"],
        count,
        constraints,
    )

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is required")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    async def event_stream():
        def _sse(event: str, data: dict[str, Any]) -> str:
            return f"event: {event}\ndata: {json.dumps(data)}\n\n"

        yield _sse("prompt", {"prompt": prompt_preview})
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload_body = {
            "model": model,
            "input": prompt_preview,
            "instructions": "You are a helpful music curator.",
            "temperature": 0.8,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "boil_playlist",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "playlist_title": {"type": "string"},
                            "arc_summary": {"type": "string"},
                            "sequence": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "title": {"type": "string"},
                                        "artist": {"type": "string"},
                                        "why": {"type": "string"},
                                        "transition": {"type": "string"},
                                        "tags": {"type": "array", "items": {"type": "string"}},
                                    },
                                    "required": [
                                        "title",
                                        "artist",
                                        "why",
                                        "transition",
                                        "tags",
                                    ],
                                },
                            },
                        },
                        "required": ["playlist_title", "arc_summary", "sequence"],
                    },
                },
            },
            "stream": True,
        }
        full_text = ""

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                "https://api.openai.com/v1/responses",
                headers=headers,
                json=payload_body,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        payload_event = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    event_type = payload_event.get("type", "")
                    if event_type == "response.output_text.delta":
                        delta = payload_event.get("delta", "")
                        if delta:
                            full_text += delta
                            yield _sse("delta", {"text": delta})
                    elif event_type == "response.error":
                        yield _sse(
                            "error",
                            {"message": payload_event.get("message", "LLM error")},
                        )

        yield _sse("done", {"text": full_text})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/resolve")
async def resolve_tracks(
    request: Request, payload: dict[str, Any] = Body(...)
) -> JSONResponse:
    sequence = payload.get("sequence") or []
    if not isinstance(sequence, list):
        raise HTTPException(status_code=400, detail="Sequence must be a list")
    spotify = await _get_spotify_client(request)
    resolved = await _resolve_sequence(spotify, sequence)
    return JSONResponse({"sequence": resolved})


@app.post("/api/resolve-one")
async def resolve_one(
    request: Request, payload: dict[str, Any] = Body(...)
) -> JSONResponse:
    title = (payload.get("title") or "").strip()
    artist = (payload.get("artist") or "").strip()
    if not title or not artist:
        raise HTTPException(status_code=400, detail="Title and artist are required")
    spotify = await _get_spotify_client(request)
    matches = await spotify.search_tracks(f"track:{title} artist:{artist}", limit=1)
    if not matches:
        matches = await spotify.search_tracks(f"track:{title}", limit=1)
    spotify_item = _simplify_track(matches[0]) if matches else None
    return JSONResponse(
        {
            "title": title,
            "artist": artist,
            "spotify": spotify_item,
            "resolved": bool(spotify_item),
        }
    )


@app.post("/api/prompt")
async def preview_prompt(
    payload: dict[str, Any] = Body(...),
) -> JSONResponse:
    start = payload.get("start") or {}
    end = payload.get("end") or {}
    count = int(payload.get("count") or 0)
    constraints = payload.get("constraints") or {}

    if not start.get("name") or not start.get("artist"):
        raise HTTPException(status_code=400, detail="Start track is required")
    if not end.get("name") or not end.get("artist"):
        raise HTTPException(status_code=400, detail="End track is required")
    if count < 1 or count > 30:
        raise HTTPException(status_code=400, detail="Count must be 1-30")

    prompt = _load_prompt()
    prompt_preview = build_prompt(
        prompt,
        start["name"],
        start["artist"],
        end["name"],
        end["artist"],
        count,
        constraints,
    )
    return JSONResponse({"prompt": prompt_preview})


@app.post("/api/playlist")
async def export_playlist(
    request: Request, payload: dict[str, Any] = Body(...)
) -> JSONResponse:
    name = (payload.get("name") or "Boil the Playlist").strip()
    description = payload.get("description") or "Generated by BoilThePlaylist"
    uris = payload.get("uris") or []

    if not uris:
        raise HTTPException(status_code=400, detail="No tracks to export")

    spotify = await _get_spotify_client(request)
    profile = await spotify.get_profile()
    playlist = await spotify.create_playlist(profile["id"], name, description)
    await spotify.add_tracks(playlist["id"], uris)

    return JSONResponse(
        {"playlist_id": playlist["id"], "playlist_url": playlist["url"]}
    )
