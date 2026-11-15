"""Native discovery entry point. Authorization runs in the separate gate command."""

def register(ctx):
    def setup(parser):
        parser.add_argument("registry")

    def validate(args):
        import importlib.util
        from pathlib import Path
        path = Path(__file__).parent / "collaborator_drive" / "registry.py"
        spec = importlib.util.spec_from_file_location("collaborator_registry_check", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.load(args.registry)
        print("Registry is structurally valid. Identity and founder approvals require operator verification.")

    ctx.register_cli_command("collaborator-check", "Validate a collaborator registry", setup, validate)
