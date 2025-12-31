import json
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx


def build_prompt(
    template: str,
    start_title: str,
    start_artist: str,
    end_title: str,
    end_artist: str,
    count: int,
    constraints: dict[str, Any] | None,
) -> str:
    normalized_constraints: dict[str, Any] = {}
    original_keys: dict[str, str] = {}
    if constraints:
        for key, value in constraints.items():
            if value is None or value == "":
                continue
            normalized_key = key.strip().lower()
            normalized_constraints[normalized_key] = value
            original_keys[normalized_key] = key.strip()

    lines = template.splitlines()
    output_lines: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("START:"):
            output_lines.append(f'START: "{start_title}" — "{start_artist}"')
            i += 1
            continue
        if stripped.startswith("END:"):
            output_lines.append(f'END: "{end_title}" — "{end_artist}"')
            i += 1
            continue
        if stripped.startswith("LENGTH:"):
            output_lines.append(f"LENGTH: N intermediate tracks = {count} (1 start + {count} + 1 end = {count + 2} total)")
            i += 1
            continue

        if stripped.startswith("CONSTRAINTS"):
            output_lines.append(line)
            i += 1
            constraint_lines: list[str] = []
            used_keys = set()
            constraint_index = 0
            while i < len(lines) and lines[i].lstrip().startswith("-"):
                raw = lines[i].lstrip()[2:]
                is_first_two = constraint_index < 2
                if "<" in raw and ">" in raw:
                    start = raw.index("<")
                    end = raw.index(">")
                    prefix = raw[:start]
                    suffix = raw[end + 1 :]
                    key = prefix.strip().rstrip(":").rstrip("?").lower()
                    value = normalized_constraints.get(key)
                    if value is not None:
                        constraint_lines.append(f"- {prefix}{value}{suffix}")
                        used_keys.add(key)
                    elif is_first_two:
                        constraint_lines.append(f"- {raw}")
                elif is_first_two:
                    constraint_lines.append(f"- {raw}")
                i += 1
                constraint_index += 1
            for key, value in normalized_constraints.items():
                if key in used_keys:
                    continue
                display_key = original_keys.get(key, key)
                constraint_lines.append(f"- {display_key}: {value}")
            if not constraint_lines:
                constraint_lines.append("- None")
            output_lines.extend(constraint_lines)
            output_lines.append("")
            while i < len(lines) and lines[i].strip() == "":
                i += 1
            continue

        output_lines.append(line)
        i += 1

    return "\n".join(output_lines).strip()


@dataclass
class LLMResult:
    sequence: list[dict[str, Any]]
    arc_summary: str
    playlist_title: str
    raw_text: str


class LLMClient:
    async def generate_playlist(
        self,
        prompt: str,
        start_title: str,
        start_artist: str,
        end_title: str,
        end_artist: str,
        count: int,
        constraints: dict[str, Any] | None,
    ) -> LLMResult:
        raise NotImplementedError


class OpenAIClient(LLMClient):
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    async def generate_playlist(
        self,
        prompt: str,
        start_title: str,
        start_artist: str,
        end_title: str,
        end_artist: str,
        count: int,
        constraints: dict[str, Any] | None,
    ) -> LLMResult:
        user_prompt = build_prompt(
            prompt,
            start_title,
            start_artist,
            end_title,
            end_artist,
            count,
            constraints,
        )
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "input": user_prompt,
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
        }

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        content = data.get("output_text", "")
        parsed = _parse_llm_output(content)

        if not parsed.sequence:
            fallback_sequence = _fallback_sequence(
                content, start_title, start_artist, end_title, end_artist
            )
            parsed = LLMResult(
                sequence=fallback_sequence,
                arc_summary="",
                playlist_title="",
                raw_text=content,
            )

        return LLMResult(
            sequence=parsed.sequence,
            arc_summary=parsed.arc_summary,
            playlist_title=parsed.playlist_title,
            raw_text=content,
        )


def _parse_llm_output(text: str) -> LLMResult:
    json_block = _extract_json_block(text)
    if not json_block:
        return LLMResult(sequence=[], arc_summary="", playlist_title="", raw_text=text)

    try:
        payload = json.loads(json_block)
    except json.JSONDecodeError:
        return LLMResult(sequence=[], arc_summary="", raw_text=text)

    sequence = payload.get("sequence") or []
    arc_summary = payload.get("arc_summary", "")
    playlist_title = payload.get("playlist_title", "")
    if not isinstance(sequence, list):
        sequence = []

    cleaned = []
    for item in sequence:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        artist = (item.get("artist") or "").strip()
        if not title or not artist:
            continue
        cleaned.append(
            {
                "title": title,
                "artist": artist,
                "why": (item.get("why") or "").strip(),
                "transition": (item.get("transition") or "").strip(),
                "tags": item.get("tags") or [],
            }
        )

    return LLMResult(
        sequence=cleaned,
        arc_summary=(arc_summary or "").strip(),
        playlist_title=(playlist_title or "").strip(),
        raw_text=text,
    )


def _extract_json_block(text: str) -> str | None:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    return None


def _fallback_sequence(
    text: str,
    start_title: str,
    start_artist: str,
    end_title: str,
    end_artist: str,
) -> list[dict[str, Any]]:
    sequence = []
    for line in text.splitlines():
        match = re.match(r"\s*\d+\.\s*(.+?)\s+—\s+(.+)$", line)
        if match:
            title = match.group(1).strip()
            artist = match.group(2).strip()
            sequence.append(
                {"title": title, "artist": artist, "why": "", "transition": ""}
            )

    if not sequence:
        return [
            {
                "title": start_title,
                "artist": start_artist,
                "why": "",
                "transition": "",
                "tags": [],
            },
            {
                "title": end_title,
                "artist": end_artist,
                "why": "",
                "transition": "",
                "tags": [],
            },
        ]

    if sequence[0]["title"].lower() != start_title.lower():
        sequence.insert(
            0,
            {
                "title": start_title,
                "artist": start_artist,
                "why": "",
                "transition": "",
                "tags": [],
            },
        )
    if sequence[-1]["title"].lower() != end_title.lower():
        sequence.append(
            {
                "title": end_title,
                "artist": end_artist,
                "why": "",
                "transition": "",
                "tags": [],
            }
        )

    return sequence


def get_llm_client() -> LLMClient:
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    if provider != "openai":
        raise ValueError(f"Unsupported LLM provider: {provider}")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is required")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    return OpenAIClient(api_key=api_key, model=model)
