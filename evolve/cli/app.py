import typer

app = typer.Typer(
    name="evolve",
    context_settings={"help_option_names": ["-h", "--help"]},
    help="Evolve - Evolving Knowledge Base Personal Agent Assistant",
    no_args_is_help=True,
)
