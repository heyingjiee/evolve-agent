from pathlib import Path
from typing import Annotated, Optional

import typer

from evolve.cli.app import app
from evolve.config import Config
from evolve.runtime import Evolve


@app.command()
def agent(
        prompt: Annotated[
            Optional[str],
            typer.Option("--prompt", "-p", help="Run a one-shot conversation with the given prompt."),
        ] = None,
        resume: Annotated[
            Optional[str],
            typer.Option("--resume", "-r", help="Resume a session by ID, or 'latest' to restore the last session."),
        ] = None,
        workspace: Annotated[
            Path,
            typer.Option("--workspace", "-w", help="Workspace directory."),
        ] = Path("."),
) -> None:
    try:
        config = Config.from_env(prompt=prompt, resume=resume, workspace=workspace)
        evolve = build_agent(config)

        if prompt:
            evolve.ask(prompt)
            return

        while True:
            try:
                user_input = input("\nEvolve > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("")
                return

            if not user_input:
                continue
            if user_input in {"/exit", "/q"}:
                break
            if user_input == "/memory":
                print(evolve.memory_text())
                continue
            if user_input == "/prompt":
                print(evolve.prompt_text())
                continue
            if user_input == "/reset":
                evolve.reset()
                print("session reset")
                continue

            evolve.ask(user_input)

    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)


def build_agent(config: Config) -> Evolve:
    if config.resume:
        return Evolve.from_session(config=config, session_id=config.resume)
    return Evolve(config=config)
