import base64
import os
import time
from typing import Any

import httpx

SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"


def _basic_auth_header(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def build_auth_url(redirect_uri: str, state: str, scope: str) -> str:
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    if not client_id:
        raise ValueError("SPOTIFY_CLIENT_ID is required")

    params = {
        "response_type": "code",
        "client_id": client_id,
        "scope": scope,
        "redirect_uri": redirect_uri,
        "state": state,
        "show_dialog": "true",
    }
    query = httpx.QueryParams(params)
    return f"https://accounts.spotify.com/authorize?{query}"


async def exchange_code_for_token(code: str, redirect_uri: str) -> dict[str, Any]:
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise ValueError("SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET are required")

    headers = {
        "Authorization": f"Basic {_basic_auth_header(client_id, client_secret)}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(SPOTIFY_TOKEN_URL, headers=headers, data=data)
        response.raise_for_status()
        token_data = response.json()

    return _normalize_token(token_data)


async def refresh_token(refresh_token: str) -> dict[str, Any]:
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise ValueError("SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET are required")

    headers = {
        "Authorization": f"Basic {_basic_auth_header(client_id, client_secret)}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(SPOTIFY_TOKEN_URL, headers=headers, data=data)
        response.raise_for_status()
        token_data = response.json()

    token_data["refresh_token"] = token_data.get("refresh_token", refresh_token)
    return _normalize_token(token_data)


def _normalize_token(token_data: dict[str, Any]) -> dict[str, Any]:
    expires_in = token_data.get("expires_in", 3600)
    token_data["expires_at"] = int(time.time()) + int(expires_in)
    return token_data


class SpotifyClient:
    def __init__(self, access_token: str) -> None:
        self.access_token = access_token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    async def search_tracks(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        params = {"q": query, "type": "track", "limit": limit}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{SPOTIFY_API_BASE}/search",
                headers=self._headers(),
                params=params,
            )
            response.raise_for_status()
            data = response.json()
        return data.get("tracks", {}).get("items", [])

    async def get_profile(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{SPOTIFY_API_BASE}/me", headers=self._headers()
            )
            response.raise_for_status()
            return response.json()

    async def create_playlist(self, user_id: str, name: str, description: str) -> dict[str, str]:
        payload = {"name": name, "description": description, "public": False}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{SPOTIFY_API_BASE}/users/{user_id}/playlists",
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        return {
            "id": data["id"],
            "url": data.get("external_urls", {}).get("spotify", ""),
        }

    async def add_tracks(self, playlist_id: str, uris: list[str]) -> None:
        payload = {"uris": uris}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/tracks",
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()


def token_is_expired(token: dict[str, Any]) -> bool:
    expires_at = token.get("expires_at", 0)
    return time.time() >= (expires_at - 60)
