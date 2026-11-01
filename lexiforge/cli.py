"""Command line entry point.

Commands are deliberately ASCII-only in their output: the harness runs on
Windows consoles whose default code page is cp1252, where ``✓``/``✗`` raise
``UnicodeEncodeError`` and kill the command.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import httpx
import typer
from rich.console import Console
from rich.table import Table

from lexiforge.canon import CANON_VERSION
from lexiforge.canon import canon as canon_key
from lexiforge.observability import get_logger

logger = get_logger(__name__)
console = Console()

app = typer.Typer(
    add_completion=False,
    help="LexiForge harness - vocabulary-budget risk testing for Gnani Prisma v3.0",
)


def _read_json(path: Path):
    """Read JSON, tolerating a UTF-8 BOM (Windows editors add one)."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


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


@app.command()
def info() -> None:
    """Show LexiForge components and matcher version."""
    table = Table(title="LexiForge")
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Description")

    table.add_row("Core harness", "ready", "Vocabulary-budget risk testing")
    table.add_row("Selector", "ready", "S = 0.55*Lex + 0.25*Phon + 0.20*Prior")
    table.add_row("Matcher", "ready", f"frozen canonicalisation {CANON_VERSION}")
    table.add_row("Prisma client", "ready", "batch + async, typed errors")
    table.add_row("Observability", "partial", "logging + metrics; tracing is local-only")
    table.add_row("Web dashboard", "ready", "API + React build (see README)")
    table.add_row("Plugin registry", "ready", "ASR backend swap point")

    console.print(table)
    console.print("\nFor Gnani Prisma v3.0 on Hinglish banking speech")


@app.command()
def optimize(
    glossary: Path = typer.Option(..., help="Path to glossary JSON"),
    hypothesis: str = typer.Option(
        ..., "--hypothesis", "-t", help="Pass-1 transcript or call text used as selection evidence"
    ),
    output: Optional[Path] = typer.Option(None, help="Write result JSON here"),
    max_terms: int = typer.Option(200, help="Maximum terms to select"),
    call_type: str = typer.Option("general", help="Call type / topic for the prior"),
) -> None:
    """Select a context list for one call using the frozen selector."""
    from lexiforge.optimizer import VocabularyOptimizer

    try:
        raw = _read_json(glossary)
        if isinstance(raw, dict):
            for key in ("terms", "glossary", "entries"):
                if isinstance(raw.get(key), list):
                    raw = raw[key]
                    break
        optimizer = VocabularyOptimizer()
        result = optimizer.optimize_context(
            hypothesis,
            glossary=raw,
            call_type=call_type,
            max_terms=max_terms,
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        console.print(f"[red]FAIL[/red] {type(exc).__name__}: {exc}")
        raise typer.Exit(code=1)

    payload = json.dumps(result, indent=2, ensure_ascii=False)
    if output:
        output.write_text(payload + "\n", encoding="utf-8")
        console.print(f"[green]OK[/green] wrote {output}")
    else:
        typer.echo(payload)

    console.print(
        f"selected {len(result['selected'])} of {int(result['metrics']['glossary_size'])} "
        f"terms at budget {result['budget']} (mean score {result['mean_score']:.4f})"
    )


@app.command()
def validate(
    config_path: Path = typer.Argument(..., help="Path to a job config JSON file"),
) -> None:
    """Validate a batch job configuration."""
    from lexiforge.api.models import BatchJobConfig

    try:
        data = _read_json(config_path)
        BatchJobConfig.model_validate(data)
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        console.print(f"[red]FAIL[/red] {type(exc).__name__}: {exc}")
        raise typer.Exit(code=1)

    console.print(f"[green]OK[/green] {config_path} is a valid job config")


@app.command()
def export_web(
    transcripts_dir: Path = typer.Option(
        Path("transcripts"), "--transcripts", help="Directory of scored transcripts"
    ),
    refs_dir: Path = typer.Option(
        Path("refs"), "--refs", help="Directory of reference transcripts"
    ),
    out_dir: Path = typer.Option(
        Path("web/data"), "--out", help="Output directory"
    ),
) -> None:
    """Export dashboard JSON from real transcripts and references.

    Replaces the illustrative sample set with measured data. See
    ``scripts/export_web_data.py`` for the file-by-file contract.
    """
    import importlib.util

    script = Path(__file__).resolve().parents[1] / "scripts" / "export_web_data.py"
    if not script.exists():
        console.print(f"[red]FAIL[/red] exporter not found at {script}")
        raise typer.Exit(code=1)

    spec = importlib.util.spec_from_file_location("export_web_data", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    try:
        written = module.export(transcripts_dir, refs_dir, out_dir)
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        console.print(f"[red]FAIL[/red] {type(exc).__name__}: {exc}")
        raise typer.Exit(code=1)

    for path in written:
        console.print(f"[green]OK[/green] wrote {path}")


if __name__ == "__main__":
    app()
