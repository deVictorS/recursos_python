#!/usr/bin/env python3
"""Monitor de recursos para Debian no terminal (CPU, memória, disco e rede)"""

import time
from typing import Dict

import psutil
from rich import box
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table

console = Console()


def format_bytes(value: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024.0:
            return f"{value:,.1f} {unit}"
        value /= 1024.0
    return f"{value:,.1f} PB"


def fetch_stats(prev_net: Dict[str, int]) -> Dict[str, object]:
    cpu = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    net = psutil.net_io_counters(pernic=False)

    stats = {
        "cpu_percent": cpu,
        "memory_total": mem.total,
        "memory_used": mem.used,
        "memory_percent": mem.percent,
        "disk_total": disk.total,
        "disk_used": disk.used,
        "disk_percent": disk.percent,
        "net_bytes_sent": net.bytes_sent,
        "net_bytes_recv": net.bytes_recv,
    }

    if prev_net:
        stats["net_upload_rate"] = (stats["net_bytes_sent"] - prev_net["sent"]) / 1.0
        stats["net_download_rate"] = (stats["net_bytes_recv"] - prev_net["recv"]) / 1.0
    else:
        stats["net_upload_rate"] = 0.0
        stats["net_download_rate"] = 0.0

    # Discos /dev/sda
    sda_partitions = []
    for part in psutil.disk_partitions(all=False):
        if part.device.startswith("/dev/sda"):
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except (PermissionError, FileNotFoundError):
                continue
            sda_partitions.append(
                {
                    "device": part.device,
                    "mountpoint": part.mountpoint,
                    "used": usage.used,
                    "total": usage.total,
                    "percent": usage.percent,
                }
            )
    stats["sda_partitions"] = sda_partitions

    # Top processos por CPU e Memória
    procs = []
    for proc in psutil.process_iter(["pid", "name", "username", "cpu_percent", "memory_percent"]):
        try:
            cpu_p = proc.cpu_percent(interval=None)
            mem_p = proc.memory_percent()
            procs.append(
                {
                    "pid": proc.pid,
                    "name": proc.info.get("name", ""),
                    "user": proc.info.get("username", ""),
                    "cpu_percent": cpu_p,
                    "memory_percent": mem_p,
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    stats["top_cpu"] = sorted(procs, key=lambda p: p["cpu_percent"], reverse=True)[:6]
    stats["top_mem"] = sorted(procs, key=lambda p: p["memory_percent"], reverse=True)[:6]

    return stats


def build_layout(stats: Dict[str, object]) -> Table:
    table = Table.grid(expand=True)
    table.add_column(ratio=1)
    table.add_column(ratio=1)

    cpu_panel = Progress(
        TextColumn("CPU {task.percentage:>5.1f}%"),
        BarColumn(bar_width=None),
        expand=True,
    )
    cpu_panel.add_task("cpu", total=100, completed=stats["cpu_percent"])

    mem_panel = Progress(
        TextColumn("RAM {task.fields[percent]:>5.1f}%"),
        BarColumn(bar_width=None),
        expand=True,
    )
    mem_panel.add_task("mem", total=100, completed=stats["memory_percent"], percent=stats["memory_percent"])

    disk_panel = Progress(
        TextColumn("DISCO {task.fields[percent]:>5.1f}%"),
        BarColumn(bar_width=None),
        expand=True,
    )
    disk_panel.add_task("disk", total=100, completed=stats["disk_percent"], percent=stats["disk_percent"])

    net_table = Table.grid(expand=True)
    net_table.add_column(justify="right")
    net_table.add_column(justify="left")
    net_table.add_row("Envio:", f"{format_bytes(int(stats['net_upload_rate']))}/s")
    net_table.add_row("Recebido:", f"{format_bytes(int(stats['net_download_rate']))}/s")

    table.add_row(
        Panel(cpu_panel, title="CPU", box=box.ROUNDED, border_style="cyan"),
        Panel(mem_panel, title="Memória", box=box.ROUNDED, border_style="green"),
    )
    table.add_row(
        Panel(disk_panel, title="Disco", box=box.ROUNDED, border_style="magenta"),
        Panel(net_table, title="Rede", box=box.ROUNDED, border_style="yellow"),
    )

    sda_table = Table(show_header=True, header_style="bold magenta", box=box.SIMPLE, expand=True)
    sda_table.add_column("DISCO")
    sda_table.add_column("MOUNT")
    sda_table.add_column("USO")

    if stats.get("sda_partitions"):
        for p in stats["sda_partitions"]:
            sda_table.add_row(
                p["device"],
                p["mountpoint"],
                f"{format_bytes(p['used'])} / {format_bytes(p['total'])} ({p['percent']:.1f}%)",
            )
    else:
        sda_table.add_row("-/dev/sda não encontrado", "", "")

    top_cpu_table = Table(show_header=True, header_style="bold cyan", box=box.SIMPLE, expand=True)
    top_cpu_table.add_column("PID")
    top_cpu_table.add_column("PROC")
    top_cpu_table.add_column("CPU%", justify="right")
    top_cpu_table.add_column("MEM%", justify="right")

    for proc in stats.get("top_cpu", []):
        top_cpu_table.add_row(
            str(proc["pid"]),
            proc["name"] or "-",
            f"{proc['cpu_percent']:.1f}",
            f"{proc['memory_percent']:.1f}",
        )

    top_mem_table = Table(show_header=True, header_style="bold green", box=box.SIMPLE, expand=True)
    top_mem_table.add_column("PID")
    top_mem_table.add_column("PROC")
    top_mem_table.add_column("CPU%", justify="right")
    top_mem_table.add_column("MEM%", justify="right")

    for proc in stats.get("top_mem", []):
        top_mem_table.add_row(
            str(proc["pid"]),
            proc["name"] or "-",
            f"{proc['cpu_percent']:.1f}",
            f"{proc['memory_percent']:.1f}",
        )

    summary_metrics = (
        f"RAM: {format_bytes(stats['memory_used'])} / {format_bytes(stats['memory_total'])} "
        f"({stats['memory_percent']:.1f}%)  "
        f"DISCO: {format_bytes(stats['disk_used'])} / {format_bytes(stats['disk_total'])} "
        f"({stats['disk_percent']:.1f}%)"
    )

    summary = Panel(summary_metrics, box=box.SIMPLE, subtitle="Use CTRL+C para sair")

    lower_panel = Table.grid(expand=True)
    lower_panel.add_column(ratio=1)
    lower_panel.add_column(ratio=1)
    lower_panel.add_row(Panel(sda_table, title="SDA partições", border_style="magenta"), Panel(top_cpu_table, title="Top CPU", border_style="cyan"))
    lower_panel.add_row(Panel(top_mem_table, title="Top MEM", border_style="green"), "")

    root = Table.grid(expand=True)
    root.add_row(table)
    root.add_row(lower_panel)
    root.add_row(summary)
    return root


def main() -> None:
    console.print("[bold green]Monitor de recursos iniciado (CPU, memória, disco, rede)[/bold green]")

    prev_net = {}
    # primeira leitura para preencher prev_net e estabilizar taxas
    prev = psutil.net_io_counters(pernic=False)
    prev_net["sent"] = prev.bytes_sent
    prev_net["recv"] = prev.bytes_recv

    try:
        with Live(console=console, refresh_per_second=2, screen=True) as live:
            while True:
                stats = fetch_stats(prev_net)
                prev_net["sent"] = stats["net_bytes_sent"]
                prev_net["recv"] = stats["net_bytes_recv"]
                live.update(build_layout(stats))
                time.sleep(1.0)
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Saindo do monitor...[/bold yellow]")


if __name__ == "__main__":
    main()
