"""Command line entry point.

Only ``doctor`` and ``canon`` exist so far: one verifies credentials without
spending audio credits, the other prints the frozen matcher key for a string so
disagreements can be debugged by hand.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import typer

from lexiforge.canon import CANON_VERSION, canon as canon_key

app = typer.Typer(add_completion=False, help="LexiForge harness")


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env loader, so the harness has no extra dependency."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


@app.command()
def doctor(
    base_url: str = typer.Option(
        None, help="Defaults to $GNANI_BASE_URL or https://api.vachana.ai"
    ),
) -> None:
    """Verify the API key and read the account's live constraints. Costs nothing."""
    _load_dotenv()
    key = os.environ.get("GNANI_API_KEY", "").strip()
    url = (base_url or os.environ.get("GNANI_BASE_URL") or "https://api.vachana.ai").rstrip("/")

    typer.echo(f"matcher version : {CANON_VERSION}")

    if not key:
        typer.secho("api key         : MISSING (set GNANI_API_KEY in .env)", fg=typer.colors.RED)
        raise typer.Exit(code=2)

    typer.echo(f"api key         : present ({len(key)} chars)")
    typer.echo(f"base url        : {url}")

    try:
        response = httpx.get(
            f"{url}/stt/v3/languages",
            headers={"X-API-Key-ID": key},
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        typer.secho(f"reachability    : FAILED ({exc})", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    typer.echo(f"http status     : {response.status_code}")

    if response.status_code != 200:
        typer.secho(f"body            : {response.text[:300]}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    payload = response.json()
    constraints = payload.get("audio_constraints", {})
    typer.secho("auth            : OK", fg=typer.colors.GREEN)

    if constraints:
        typer.echo(f"max duration    : {constraints.get('max_duration_seconds')} s")
        formats = constraints.get("supported_formats") or []
        typer.echo(f"formats         : {', '.join(formats) if formats else 'not reported'}")

    models = payload.get("models") or payload.get("supported_models")
    if models:
        typer.echo(f"models          : {json.dumps(models)[:300]}")


@app.command()
def canon(text: str = typer.Argument(..., help="Surface form to canonicalise")) -> None:
    """Print the frozen matching key for a term or phrase."""
    key = canon_key(text)
    typer.echo(f"input  : {text!r}")
    typer.echo(f"key    : {key!r}")
    typer.echo(f"tokens : {key.split()}")


if __name__ == "__main__":
    app()
