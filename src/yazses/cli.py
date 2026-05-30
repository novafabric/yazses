"""YazSes CLI. Talks to the daemon over IPC where possible, with a
PID-file fallback for status.
"""

from importlib.metadata import version as _pkg_version
from typing import Optional

import typer

from yazses.ipc.client import IpcUnreachableError
from yazses.platform import get_platform

app = typer.Typer(name="yazses", help="Local voice dictation daemon.")

model_app = typer.Typer(name="model", help="Manage SLM intent-routing models.")
app.add_typer(model_app)

corpus_app = typer.Typer(name="corpus", help="Manage the local learning corpus.")
app.add_typer(corpus_app)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"yazses {_pkg_version('yazses')}")
        raise typer.Exit()


@app.callback()
def _main(
    version: Optional[bool] = typer.Option(
        None, "--version", callback=_version_callback, is_eager=True, help="Show version and exit."
    ),
) -> None:
    pass


@app.command()
def start() -> None:
    """Start the YazSes daemon in the background."""
    platform = get_platform()
    if platform.lifecycle.is_running():
        typer.echo("YazSes is already running.")
        raise typer.Exit(1)
    # Clear any stale PID file left by a crashed daemon.
    platform.lifecycle.clear_pid()
    platform.lifecycle.start_daemon_detached()
    typer.echo(f"YazSes started. Hold {platform.default_hotkey} to dictate.")


@app.command()
def stop() -> None:
    """Stop the running daemon."""
    platform = get_platform()
    pid = platform.lifecycle.read_pid()
    if pid is None or not platform.lifecycle.is_running():
        typer.echo("YazSes is not running.")
        raise typer.Exit(1)
    platform.lifecycle.stop_daemon(pid)
    typer.echo("YazSes stopped.")


@app.command()
def status() -> None:
    """Show daemon status. Queries the daemon over IPC when reachable."""
    platform = get_platform()
    if not platform.lifecycle.is_running():
        typer.echo("YazSes is not running.")
        return

    pid = platform.lifecycle.read_pid()
    client = platform.ipc_client_factory(platform.paths.ipc_socket)
    try:
        info = client.call("status")
    except IpcUnreachableError:
        typer.echo(f"YazSes is running (PID {pid}); IPC not yet ready.")
        return

    typer.echo(f"YazSes is running (PID {pid}).")
    typer.echo(f"  state:    {info.get('state')}")
    typer.echo(f"  hotkey:   {info.get('hotkey')}")
    typer.echo(f"  model:    {info.get('model')}")
    typer.echo(f"  backend:  {info.get('injection_backend')}")
    typer.echo(f"  uptime:   {info.get('uptime_s')}s")
    if info.get("last_error"):
        typer.echo(f"  last err: {info['last_error']}")


@app.command()
def doctor() -> None:
    """Check system prerequisites."""
    from yazses.system.doctor import run_doctor

    run_doctor()


@app.command(name="mic-level")
def mic_level(
    seconds: float = typer.Option(4.0, "--seconds", "-s", help="Seconds to record while you speak."),
    set_threshold: bool = typer.Option(False, "--set", help="Write the recommended vad_threshold to config."),
) -> None:
    """Measure mic speech level and recommend (or set) the VAD threshold.

    Speak in a normal voice for the whole countdown. The daemon discards a clip
    when its average level is below vad_threshold, so if dictation shows
    "Silent audio -- discarding", run this to find a level that fits your voice.
    """
    from yazses.config import load_config
    from yazses.system.miclevel import analyze, record, update_threshold_in_config

    platform = get_platform()
    cfg = load_config(platform.paths.config_file)
    sr = cfg.audio.sample_rate

    typer.echo(f"Recording {seconds:.0f}s -- speak normally now...")
    stats = analyze(record(seconds, sr), sr)

    typer.echo(f"  mean level:            {stats.mean_abs:.4f}")
    typer.echo(f"  peak level:            {stats.peak:.4f}")
    typer.echo(f"  current vad_threshold: {cfg.accessibility.vad_threshold}")

    if stats.is_silent:
        typer.echo("No speech detected -- check the microphone and try again.")
        raise typer.Exit(code=1)

    rec = stats.recommended_threshold
    typer.echo(f"  recommended:           {rec}")

    if set_threshold:
        msg = update_threshold_in_config(platform.paths.config_file, rec)
        typer.echo(f"Applied: {msg}")
        typer.echo("Restart to pick it up:  yazses stop && yazses start")
    else:
        typer.echo("Re-run with --set to apply, or put in config.toml:")
        typer.echo(f"  [accessibility]\n  vad_threshold = {rec}")


@app.command()
def logs(
    lines: int = typer.Option(40, "--lines", "-n", help="Number of recent lines to show."),
    path_only: bool = typer.Option(False, "--path", help="Print the log file path and exit."),
) -> None:
    """Show the daemon's diagnostic log (metadata only -- no dictated text)."""
    platform = get_platform()
    log_file = platform.paths.log_dir / "daemon.log"
    if path_only:
        typer.echo(str(log_file))
        return
    if not log_file.exists():
        typer.echo(f"No log yet at {log_file} -- start the daemon first.")
        raise typer.Exit(code=1)
    content = log_file.read_text(errors="replace").splitlines()
    for line in content[-lines:]:
        typer.echo(line)
    typer.echo(f"\n({log_file} -- follow live with: tail -f {log_file})")


@app.command()
def inject(text: str = typer.Argument(..., help="Text to inject into the focused app.")) -> None:
    """Test text injection without recording."""
    platform = get_platform()
    injector = platform.injector_factory()
    typer.echo(f"Backend: {type(injector).__name__}")
    injector.inject(text)
    typer.echo(f"Injected: {text!r}")


@app.command()
def overlay() -> None:
    """Run the sonar voice-activity overlay (needs the `overlay` extra: PySide6).

    Draws neon rings near the cursor that pulse with your voice while dictating.
    Normally auto-launched by the daemon when `[overlay] enabled = true`; run it
    here in the foreground to preview or debug it.
    """
    from yazses.overlay.app import run as run_overlay

    run_overlay()


@app.command()
def remote(
    host: str = typer.Argument(..., help="SSH host to forward voice typing to."),
    port: int = typer.Option(22, "--port", "-p", help="SSH port."),
    key_file: str = typer.Option("", "--key-file", "-i", help="Path to SSH private key."),
    stop: bool = typer.Option(False, "--stop", help="Disconnect active remote session."),
) -> None:
    """Forward voice typing to a remote host over SSH."""
    platform = get_platform()
    client = platform.ipc_client_factory(platform.paths.ipc_socket)
    try:
        if stop:
            result = client.call("remote_stop")
            typer.echo("Remote session disconnected." if result.get("ok") else f"Error: {result}")
        else:
            result = client.call("remote_start", host=host, port=port, key_file=key_file)
            if result.get("ok"):
                typer.echo(f"Connecting to {host}:{port}... (use --stop to disconnect)")
            else:
                typer.echo(f"Error: {result.get('reason', result)}", err=True)
                raise typer.Exit(1)
    except IpcUnreachableError:
        typer.echo("Daemon is not running. Start it with: yazses start", err=True)
        raise typer.Exit(1)


@app.command()
def enroll() -> None:
    """Run the accessibility enrollment wizard to calibrate VAD thresholds.

    Records 20 short utterances to derive vad_threshold and min_silence_ms
    values tuned to your voice and microphone. Results are written to config.toml.
    """
    platform = get_platform()
    client = platform.ipc_client_factory(platform.paths.ipc_socket)
    if client.is_reachable():
        try:
            result = client.call("enroll_start")
            if result.get("ok"):
                typer.echo("Enrollment started. Follow the prompts in the daemon terminal.")
            else:
                typer.echo(f"Error: {result.get('reason', result)}", err=True)
                raise typer.Exit(1)
        except IpcUnreachableError:
            pass
    else:
        # Run wizard locally when daemon is not running
        from yazses.accessibility.enroll import run_wizard
        run_wizard(config_path=platform.paths.config_file)


@model_app.command("list")
def model_list() -> None:
    """List available SLM models and their download status."""
    from yazses.commands.model_manager import list_models, local_path

    for info in list_models():
        path = local_path(info.id)
        status = f"installed: {path}" if path else f"not downloaded ({info.size_mb} MB)"
        typer.echo(f"  {info.id:<24}  {info.description}")
        typer.echo(f"  {'':24}  [{status}]")
        typer.echo("")


@model_app.command("download")
def model_download(
    model_id: str = typer.Argument(..., help="Model ID (see `yazses model list`)."),
) -> None:
    """Download a GGUF model for Tier 2 SLM intent routing."""
    from yazses.commands.model_manager import download_model

    try:
        path = download_model(model_id)
        typer.echo("\nDone. Add this to your config.toml:")
        typer.echo("  [commands]")
        typer.echo(f'  slm_model_path = "{path}"')
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
    except Exception as exc:
        typer.echo(f"Download failed: {exc}", err=True)
        raise typer.Exit(1)


@app.command(name="mark-wrong")
def mark_wrong(
    correction: str = typer.Option(
        "", "--correction", "-c", help="What you actually said (optional)."
    ),
) -> None:
    """Flag the last dictation as a misrecognition (a learning signal).

    Requires `[learning] enabled = true`. Routes through the running daemon so
    the flag lands on the event it just captured.
    """
    platform = get_platform()
    client = platform.ipc_client_factory(platform.paths.ipc_socket)
    try:
        result = client.call("mark_last_wrong", correction=correction or None)
    except IpcUnreachableError:
        typer.echo("Daemon is not running. Start it with: yazses start", err=True)
        raise typer.Exit(1)
    if result.get("ok"):
        typer.echo("Flagged the last dictation as wrong. `yazses tune` will use it.")
    else:
        typer.echo(f"Could not flag: {result.get('reason', 'no recent event')}", err=True)
        raise typer.Exit(1)


@app.command()
def tune(
    apply: bool = typer.Option(False, "--apply", help="Review and apply proposals interactively."),
    retranscribe: bool = typer.Option(
        True, "--retranscribe/--no-retranscribe",
        help="Re-transcribe captured audio with a larger model to find errors.",
    ),
) -> None:
    """Analyze the learning corpus and propose accuracy improvements.

    Dry-run by default: prints proposed config changes (vocabulary, VAD
    threshold, model, disfluency rules, SLM few-shots). Use --apply to choose
    which to write to config.toml.
    """
    from yazses.config import load_config
    from yazses.learning.capture import open_store
    from yazses.learning.tuner import run_tune

    platform = get_platform()
    data_dir = platform.paths.data_dir
    if not (data_dir / "corpus.db").exists():
        typer.echo(
            "No corpus yet. Enable it with `[learning] enabled = true` in "
            f"{platform.paths.config_file}, then dictate for a while.",
            err=True,
        )
        raise typer.Exit(1)

    cfg = load_config(platform.paths.config_file)
    store = open_store(data_dir)

    transcribe_fn = None
    if retranscribe:
        from yazses.stt.faster_whisper import FasterWhisperEngine

        typer.echo(f"Loading re-transcription model '{cfg.learning.tune_model}'...")
        engine = FasterWhisperEngine(
            model_name=cfg.learning.tune_model,
            device=cfg.stt.device,
            compute_type=cfg.stt.compute_type,
        )
        transcribe_fn = engine.transcribe

    try:
        run_tune(
            store,
            cfg,
            platform.paths.config_file,
            data_dir / "few_shots.toml",
            do_apply=apply,
            do_retranscribe=retranscribe,
            transcribe_fn=transcribe_fn,
            echo=typer.echo,
            confirm=typer.confirm,
        )
    finally:
        store.close()


@corpus_app.command("status")
def corpus_status() -> None:
    """Show the learning corpus size, event counts, and date range."""
    import datetime as _dt

    from yazses.learning.capture import open_store

    platform = get_platform()
    data_dir = platform.paths.data_dir
    if not (data_dir / "corpus.db").exists():
        typer.echo("No corpus yet (learning capture is off or unused).")
        return
    store = open_store(data_dir)
    try:
        s = store.stats()
    finally:
        store.close()

    def _fmt(ts):
        return _dt.datetime.fromtimestamp(ts).isoformat(timespec="seconds") if ts else "-"

    typer.echo(f"  location:  {data_dir}")
    typer.echo(f"  events:    {s.count} ({s.discarded} discarded, {s.wrong} flagged wrong)")
    typer.echo(f"  size:      {s.size_bytes / 1_048_576:.1f} MB")
    typer.echo(f"  range:     {_fmt(s.oldest_ts)} → {_fmt(s.newest_ts)}")


@corpus_app.command("forget")
def corpus_forget(
    minutes: float = typer.Option(..., "--minutes", "-m", help="Delete events from the last N minutes."),
) -> None:
    """Delete recently captured events (e.g. after dictating something private)."""
    from yazses.learning.capture import open_store

    platform = get_platform()
    if not (platform.paths.data_dir / "corpus.db").exists():
        typer.echo("No corpus to forget from.")
        return
    store = open_store(platform.paths.data_dir)
    try:
        n = store.forget(minutes)
    finally:
        store.close()
    typer.echo(f"Forgot {n} event(s) from the last {minutes:g} minute(s).")


@corpus_app.command("destroy")
def corpus_destroy(
    confirm: bool = typer.Option(False, "--i-mean-it", help="Required: confirm irreversible wipe."),
) -> None:
    """Irreversibly delete the entire learning corpus (database + audio clips)."""
    from yazses.learning.capture import open_store

    platform = get_platform()
    if not confirm:
        typer.echo("Refusing without --i-mean-it (this is irreversible).", err=True)
        raise typer.Exit(1)
    if not (platform.paths.data_dir / "corpus.db").exists():
        typer.echo("No corpus to destroy.")
        return
    store = open_store(platform.paths.data_dir)
    store.destroy()
    typer.echo("Learning corpus destroyed.")


@app.command()
def test() -> None:
    """End-to-end self-test: confirm the injector works without speaking.

    Focus a text editor first; this command types `YazSes OK` into the
    focused window. If you see those words appear, injection is working.
    """
    platform = get_platform()
    typer.echo(f"Platform: {platform.name}")
    typer.echo(f"Hotkey:   {platform.default_hotkey}")
    typer.echo(f"Config:   {platform.paths.config_file}")
    typer.echo("")
    typer.echo("Focus a text editor or browser address bar.")
    typer.echo("Typing 'YazSes OK' into the focused window in 3 seconds...")
    import time

    for i in range(3, 0, -1):
        typer.echo(f"  {i}...")
        time.sleep(1)

    # If the daemon's running, route through it (closer to real hold-to-talk
    # path); otherwise fall back to a local injector.
    client = platform.ipc_client_factory(platform.paths.ipc_socket)
    if client.is_reachable():
        typer.echo("Routing through running daemon over IPC.")
        try:
            from yazses.ipc.client import IpcCallError

            result = client.call("inject", text="YazSes OK")
            typer.echo(f"Result: {result}")
            return
        except IpcCallError as exc:
            typer.echo(f"Daemon inject failed ({exc}); falling back to local.")

    injector = platform.injector_factory()
    typer.echo(f"Local injector: {type(injector).__name__}")
    injector.inject("YazSes OK")
    typer.echo("Done. If you saw 'YazSes OK' appear, injection works.")
