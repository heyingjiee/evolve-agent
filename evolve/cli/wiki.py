import typer

from evolve.cli.app import app


@app.command()
def wiki():
    """ 管理知识库."""
    typer.echo("Wiki command...")
