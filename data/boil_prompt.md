You are a music curator and DJ. Build me a “Boil the Frog” transition playlist that morphs from a START track to an END track through smooth, incremental steps.

GOAL
- The playlist must start with the START track and end with the END track.
- Between them, include N intermediate tracks that gradually interpolate from START → END.
- Each adjacent pair should feel like a natural transition (small change), while the overall arc clearly shifts to match the END track (large change).

INPUTS
START: "<song title>" — "<artist>"
END: "<song title>" — "<artist>"
LENGTH: N intermediate tracks = <number>  (total playlist length = N + 2)
CONSTRAINTS:
- Avoid repeating the same artist more than <k> times
- Do not include both a song and its remix
- Include/exclude explicit lyrics: <yes/no>
- Keep within genre boundaries? <tight/medium/loose>
- Energy arc: <rising / falling / wave / steady>
- Era constraints: <e.g., 1990–2025> or “any”
- Must include at least <m> female-fronted tracks / live versions / instrumentals / etc.
- Region preference: <US/UK/Global/etc.>

METHOD (do this explicitly)
1) Analyze START and END along these “audio identity” dimensions (describe in plain English):
   - genre + subgenre, tempo/drive, energy, mood/valence, instrumentation/texture,
     vocals style, production era (lo-fi/hi-fi), aggressiveness, danceability,
     harmonic vibe (bright/dark), lyrical themes (optional).
2) Choose 3–6 key dimensions that best define the distance from START → END.
3) Create a transition plan broken into 3–5 phases (e.g., Phase 1 = mostly START DNA,
   final phase = mostly END DNA). Each phase should state what changes.
4) Pick tracks that satisfy the phase targets and maximize smoothness between neighbors.
   - Keep changes between consecutive tracks small and mostly along 1–2 dimensions at a time.
   - Make the direction monotonic overall: less like START, more like END as you go.
5) Self-check: for each adjacent pair, give a short reason the transition works.
6) Output requirements to encode in JSON:
   - Provide a creative playlist_title that references the songs or vibes.
   - Include the full ordered sequence (START first, END last).
   - For each intermediate track, include why + transition + tags.
   - Provide a fun, DJ-like arc_summary (2–4 sentences).

OUTPUT FORMAT
Return ONLY a JSON object with this shape (no extra prose):
{
  "playlist_title": "string",
  "arc_summary": "string",
  "sequence": [
    {
      "title": "string",
      "artist": "string",
      "why": "string",
      "transition": "string",
      "tags": ["string"]
    }
  ]
}
Rules:
- Include START as the first element and END as the last element.
- Keep arc_summary casual, fun, and DJ-like (2–4 sentences).

OPTIONAL (if you have Spotify/audio-feature access)
- Use Spotify audio features (danceability, energy, tempo, valence, acousticness, etc.)
  to justify the path. Keep the feature drift smooth between neighbors.
- Ensure tracks are available on Spotify; prefer the most-streamed/primary version.

Now build the playlist.
