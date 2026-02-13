"""CLI entry point for the Koda2 Self-Healing Supervisor."""

from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(help="Koda2 Self-Healing Supervisor", no_args_is_help=True)
console = Console()


@app.command()
def run(
    no_repair: bool = typer.Option(False, "--no-repair", help="Disable auto-repair on crash"),
    no_evolution: bool = typer.Option(False, "--no-evolution", help="Disable evolution loop"),
) -> None:
    """Start Koda2 under the self-healing supervisor."""
    from koda2.supervisor.safety import SafetyGuard
    from koda2.supervisor.monitor import ProcessMonitor
    from koda2.supervisor.repair import RepairEngine

    console.print("\n[bold cyan]🧬 Koda2 Self-Healing Supervisor[/bold cyan]\n")

    safety = SafetyGuard()
    repair = RepairEngine(safety) if not no_repair else None

    async def on_crash(stderr: str, exit_code: int) -> None:
        """Handle a crash — attempt self-repair."""
        console.print(f"\n[bold red]💥 Koda2 crashed (exit code {exit_code})[/bold red]")

        if repair and safety.can_attempt_repair(stderr):
            console.print("[yellow]🔧 Attempting self-repair...[/yellow]")
            success, message = await repair.attempt_repair(stderr)
            if success:
                console.print(f"[bold green]✅ Self-repair successful:[/bold green] {message}")
            else:
                console.print(f"[red]❌ Self-repair failed:[/red] {message}")
        else:
            console.print("[yellow]⚠ Auto-repair disabled or attempts exhausted[/yellow]")

        console.print("[cyan]🔄 Restarting Koda2...[/cyan]\n")

    monitor = ProcessMonitor(safety, on_crash=on_crash)

    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        console.print("\n[yellow]Shutting down supervisor...[/yellow]")
        monitor.shutdown()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    console.print("[green]Starting Koda2 with self-healing enabled...[/green]")
    console.print(f"  Auto-repair: {'[green]ON[/green]' if repair else '[red]OFF[/red]'}")
    console.print(f"  Evolution:   {'[green]ON[/green]' if not no_evolution else '[red]OFF[/red]'}")
    console.print()

    safety.audit("supervisor_cli_start", {
        "repair": not no_repair,
        "evolution": not no_evolution,
    })

    asyncio.run(monitor.run())


@app.command()
def repair(
    stderr_file: str = typer.Argument(None, help="File containing stderr output to analyze"),
) -> None:
    """Manually trigger crash analysis and repair."""
    from koda2.supervisor.safety import SafetyGuard
    from koda2.supervisor.repair import RepairEngine

    safety = SafetyGuard()
    engine = RepairEngine(safety)

    if stderr_file:
        stderr = Path(stderr_file).read_text()
    else:
        console.print("Paste the error/traceback (Ctrl+D when done):")
        stderr = sys.stdin.read()

    if not stderr.strip():
        console.print("[red]No error input provided[/red]")
        raise typer.Exit(1)

    console.print("\n[cyan]🔍 Analyzing crash...[/cyan]")

    async def _repair():
        success, message = await engine.attempt_repair(stderr)
        if success:
            console.print(f"\n[bold green]✅ Repair successful:[/bold green] {message}")
        else:
            console.print(f"\n[red]❌ Repair failed:[/red] {message}")

    asyncio.run(_repair())


@app.command()
def improve(
    request: str = typer.Argument(..., help="Description of the improvement to make"),
) -> None:
    """Request a code improvement via LLM."""
    from koda2.supervisor.safety import SafetyGuard
    from koda2.supervisor.evolution import EvolutionEngine

    safety = SafetyGuard()
    engine = EvolutionEngine(safety)

    console.print(f"\n[cyan]🧬 Planning improvement:[/cyan] {request}\n")

    async def _improve():
        success, message = await engine.implement_improvement(request)
        if success:
            console.print(f"\n[bold green]✅ Improvement applied:[/bold green]\n{message}")
        else:
            console.print(f"\n[red]❌ Improvement failed:[/red]\n{message}")

    asyncio.run(_improve())


@app.command()
def status() -> None:
    """Show supervisor status and recent activity."""
    from koda2.supervisor.safety import AUDIT_LOG_FILE, REPAIR_STATE_FILE
    import json

    console.print("\n[bold cyan]🧬 Supervisor Status[/bold cyan]\n")

    # Repair state
    if REPAIR_STATE_FILE.exists():
        try:
            state = json.loads(REPAIR_STATE_FILE.read_text())
            counts = state.get("repair_counts", {})
            if counts:
                console.print("[bold]Repair Attempts:[/bold]")
                for sig, count in counts.items():
                    console.print(f"  {sig[:80]}: {count}/3 attempts")
            else:
                console.print("[green]No active repair cycles[/green]")
            console.print(f"  Last updated: {state.get('updated_at', 'unknown')}")
        except Exception:
            console.print("[yellow]Could not read repair state[/yellow]")
    else:
        console.print("[green]No repair state (clean)[/green]")

    # Recent audit log
    console.print()
    if AUDIT_LOG_FILE.exists():
        lines = AUDIT_LOG_FILE.read_text().strip().splitlines()
        recent = lines[-10:] if len(lines) > 10 else lines
        console.print(f"[bold]Recent Activity ({len(lines)} total entries):[/bold]")
        for line in recent:
            try:
                entry = json.loads(line)
                ts = entry.get("timestamp", "")[:19]
                action = entry.get("action", "unknown")
                console.print(f"  {ts} — {action}")
            except Exception:
                continue
    else:
        console.print("[dim]No audit log yet[/dim]")

    console.print()


if __name__ == "__main__":
    app()
