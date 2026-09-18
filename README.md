# Lumina

Standalone web-first **drone show compiler**. Not a flight controller, not a Blender plugin, not a Skybrush fork.

```
artwork → dshowc → .dshow → vendor exporters
```

Canonical model: **DSHOW_LOCAL_RH** (`+X` right, `+Y` toward audience, `+Z` up). See `docs/`.

## What v0.1 proves

1. Create a project and set drone count (10–500)
2. Import SVG (or load the Dragon demo)
3. Compiler emits **exactly N** points per formation
4. Hungarian assignment + min-jerk trajectories
5. Safety report (separation, velocity, acceleration)
6. Realtime Three.js rehearsal
7. Export `.dshow`, generic CSV, **VVIZ (viz only)**, Skybrush-compatible CSV

## Local development

```bash
python -m pip install -r apps/compiler-api/requirements.txt
python -m uvicorn app.main:app --reload --app-dir apps/compiler-api --port 8000

npm install
npm run dev
```

Web: http://localhost:3000  
Compiler: http://localhost:8000/docs

```bash
python -m pytest apps/compiler-api/tests
```

`docker compose up --build` runs both services.

## Architecture

| Layer | Owner |
| --- | --- |
| Formation / assignment / trajectory / safety / export | Python `dshowc` |
| Timeline, viewport, playback | Next.js + `@lumina/simulator` |
| Show file | `.dshow` ZIP |

Do not bind formation point identity to a physical drone. Do not copy GPL Skybrush source. VVIZ is visualization, not flight.

## Licensing

See `docs/licensing.md`.
