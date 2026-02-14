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
    no_learning: bool = typer.Option(False, "--no-learning", help="Disable continuous learning loop"),
    notify_user: str = typer.Option("", "--notify", help="WhatsApp user ID to notify on improvements"),
) -> None:
    """Start Koda2 under the self-healing supervisor."""
    from koda2.supervisor.safety import SafetyGuard
    from koda2.supervisor.monitor import ProcessMonitor
    from koda2.supervisor.repair import RepairEngine
    from koda2.supervisor.learner import ContinuousLearner

    console.print("\n[bold cyan]🧬 Koda2 Self-Healing Supervisor[/bold cyan]\n")

    safety = SafetyGuard()
    repair = RepairEngine(safety) if not no_repair else None
    learner = ContinuousLearner(safety, notify_user_id=notify_user or None) if not no_learning else None

    from koda2.supervisor.notifier import SupervisorNotifier
    notifier = SupervisorNotifier(user_id=notify_user or None)

    async def on_crash(stderr: str, exit_code: int) -> None:
        """Handle a crash — attempt self-repair, notify user."""
        console.print(f"\n[bold red]💥 Koda2 crashed (exit code {exit_code})[/bold red]")

        repaired = False
        diagnosis = ""

        if repair and safety.can_attempt_repair(stderr):
            console.print("[yellow]🔧 Attempting self-repair...[/yellow]")
            success, message = await repair.attempt_repair(stderr)
            repaired = success
            diagnosis = message
            if success:
                console.print(f"[bold green]✅ Self-repair successful:[/bold green] {message}")
            else:
                console.print(f"[red]❌ Self-repair failed:[/red] {message}")
        else:
            console.print("[yellow]⚠ Auto-repair disabled or attempts exhausted[/yellow]")

        # Notify user about crash + restart
        await notifier.notify_crash_and_restart(exit_code, repaired, diagnosis)

        console.print("[cyan]🔄 Restarting Koda2...[/cyan]\n")

    monitor = ProcessMonitor(safety, on_crash=on_crash)

    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        console.print("\n[yellow]Shutting down supervisor...[/yellow]")
        if learner:
            learner.stop()
        monitor.shutdown()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    console.print("[green]Starting Koda2 with self-healing enabled...[/green]")
    console.print(f"  Auto-repair: {'[green]ON[/green]' if repair else '[red]OFF[/red]'}")
    console.print(f"  Evolution:   {'[green]ON[/green]' if not no_evolution else '[red]OFF[/red]'}")
    console.print(f"  Learning:    {'[green]ON[/green]' if learner else '[red]OFF[/red]'}")
    if notify_user:
        console.print(f"  Notify:      [green]{notify_user}[/green]")
    console.print()

    safety.audit("supervisor_cli_start", {
        "repair": not no_repair,
        "evolution": not no_evolution,
        "learning": not no_learning,
        "notify_user": notify_user or None,
    })

    async def _run_all():
        """Run monitor, learner, and improvement queue workers concurrently."""
        from koda2.supervisor.improvement_queue import get_improvement_queue

        tasks = [monitor.run()]
        if learner:
            tasks.append(learner.run_forever())

        # Start improvement queue workers so queued items get processed
        if not no_evolution:
            queue = get_improvement_queue()
            queue.start_worker()
            console.print(f"  Workers:     [green]{queue.max_workers} queue workers[/green]")

        await asyncio.gather(*tasks)

    asyncio.run(_run_all())


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
def learn(
    notify_user: str = typer.Option("", "--notify", help="WhatsApp user ID to notify on improvements"),
) -> None:
    """Run one learning cycle manually (analyze logs + conversations → improve)."""
    from koda2.supervisor.safety import SafetyGuard
    from koda2.supervisor.learner import ContinuousLearner

    safety = SafetyGuard()
    learner = ContinuousLearner(safety, notify_user_id=notify_user or None)

    console.print("\n[cyan]🧠 Running learning cycle...[/cyan]\n")

    async def _learn():
        summary = await learner.run_cycle()
        console.print(f"[bold]Cycle #{summary['cycle']}[/bold]")
        console.print(f"  Signals gathered:     {summary['signals_gathered']}")
        console.print(f"  Proposals generated:  {summary['proposals']}")
        console.print(f"  Improvements applied: {summary['improvements_applied']}")
        console.print(f"  Improvements failed:  {summary['improvements_failed']}")
        if summary.get('version_bumped'):
            console.print(f"  [green]Version bumped to: {summary.get('new_version')}[/green]")
        if summary.get('user_notified'):
            console.print(f"  [green]User notified via WhatsApp[/green]")
        if summary.get('error'):
            console.print(f"  [red]Error: {summary['error']}[/red]")
        console.print()

    asyncio.run(_learn())


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

    # Learner state
    learner_state = Path("data/supervisor/learner_state.json")
    console.print()
    if learner_state.exists():
        try:
            ls = json.loads(learner_state.read_text())
            console.print(f"[bold]Learning Loop:[/bold]")
            console.print(f"  Cycles completed: {ls.get('cycle_count', 0)}")
            console.print(f"  Improvements applied: {len(ls.get('improvements_applied', []))}")
            console.print(f"  Failed ideas (skipped): {len(ls.get('failed_ideas', []))}")
            console.print(f"  Last updated: {ls.get('updated_at', 'unknown')}")
        except Exception:
            console.print("[yellow]Could not read learner state[/yellow]")
    else:
        console.print("[dim]No learning cycles yet[/dim]")

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


@app.command()
def queue(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of items to show"),
) -> None:
    """Show improvement queue status and recent items."""
    from koda2.supervisor.improvement_queue import get_improvement_queue

    q = get_improvement_queue()
    stats = q.stats()

    console.print("\n[bold cyan]🧬 Improvement Queue[/bold cyan]\n")
    console.print(f"  Total items:     {stats['total']}")
    console.print(f"  Pending:         {stats['pending']}")
    console.print(f"  Planning:        {stats['planning']}")
    console.print(f"  In progress:     {stats['in_progress']}")
    console.print(f"  Completed:       [green]{stats['completed']}[/green]")
    console.print(f"  Failed:          [red]{stats['failed']}[/red]")
    console.print(f"  Skipped:         {stats['skipped']}")
    console.print(f"  Max workers:     {stats['max_workers']}")
    console.print()

    items = q.list_items(limit=limit)
    if items:
        console.print("[bold]Recent items:[/bold]")
        for item in items[-limit:]:
            status_color = {
                "pending": "yellow",
                "planning": "cyan",
                "in_progress": "blue",
                "completed": "green",
                "failed": "red",
                "skipped": "dim",
            }.get(item["status"], "white")
            source = item.get("source", "?")
            request = item.get("request", "")[:60]
            console.print(
                f"  [{status_color}]{item['status']:12s}[/{status_color}] "
                f"[dim]{item['id']}[/dim] [{source}] {request}"
            )
    console.print()


if __name__ == "__main__":
    app()
