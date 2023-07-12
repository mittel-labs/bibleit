import argparse

from bibleit import config, bible

parser = argparse.ArgumentParser(
    prog=config.application,
    description=f"{config.application} v{config.version}",
    allow_abbrev=False,
)

parser.add_argument(
    "--version", action="version", version=f"{config.application} v{config.version}"
)
parser.add_argument("--repl", action="store_true", help="Opens bibleit REPL")
parser.add_argument(
    "--linesep",
    type=int,
    choices=range(0, 11),
    metavar="value",
    help="Configure line separator",
)
parser.add_argument(
    "--bible",
    choices=bible.get_available_bibles(),
    action="append",
    metavar="value",
    help="Use one or more Bible translations",
)
parser.add_argument("args", nargs="*", help="Arguments to be evaluated")

for flag in config.flag_names:
    parser.add_argument(
        f"--{flag}",
        action="store_true",
        dest=f"flag_{flag}",
        help=f"Enable {flag} flag",
    )
