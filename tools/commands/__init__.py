"""Subcommands of `python -m tools`, one module each.

Every module here is a command and must define:
  NAME                  subcommand name
  HELP                  one-line description shown in --help
  add_arguments(parser) adds the command's options to its argparse parser
  run(args) -> int      does the work; the return value is the exit code
"""
