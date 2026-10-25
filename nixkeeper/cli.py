"""Run the `nixkeeper` command: the sync, the hourly checks and the rest.

It's one entry point, with the settings as flags (see each command's
--help):

    nixkeeper sync | frequent-check | pr-check | paths [--lists PATH]
              [--data-dir DIR] [--notify METHOD]
    nixkeeper init [--maintainer HANDLE ...] [--lists PATH]
    nixkeeper page DIR | serve [--port PORT] [--bind ADDRESS]  [--data-dir DIR]
    nixkeeper community-check [NAME ...] [--file PATH] [--changed-from DIR]
              [--report-issue]
    nixkeeper --version

Each flag wins over its environment variable (NIXKEEPER_LISTS,
NIXKEEPER_DATA_DIR, NIXKEEPER_NOTIFY), which wins over the default: the
user's own folders (config.py). The old commands (nixkeeper-sync,
nixkeeper-frequent-check, nixkeeper-pr-check) still work until 1.0, as
aliases.
"""

import argparse
import importlib
import os
import sys
from datetime import UTC, datetime

from . import community, config, history, init, lock, notify, page, version

# {name: (what it does, the module whose main() runs it)}
COMMANDS = {
    "sync": (
        "one full sync: every source, for every tracked package",
        "nixkeeper.sync",
    ),
    "frequent-check": (
        "only the update checks marked frequent, against the last published data",
        "nixkeeper.frequent",
    ),
    "pr-check": (
        "outdated packages' update PRs, open and merged, against the last "
        "published data",
        "nixkeeper.prcheck",
    ),
}

# {flag: (the config setting it sets, its environment variable)}
SETTINGS = {
    "lists": ("LISTS", "NIXKEEPER_LISTS"),
    "data_dir": ("OUT_DIR", "NIXKEEPER_DATA_DIR"),
    "notify": ("NOTIFY", "NIXKEEPER_NOTIFY"),
}


def parser():
    """Build the command's argument parser."""
    # The settings, accepted before or after the command. SUPPRESS: a flag
    # left out doesn't overwrite one given in the other position.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--lists",
        metavar="PATH",
        default=argparse.SUPPRESS,
        help="the package lists: a Nix folder (package-lists/) or a JSON file "
        "of what it evaluates to (NIXKEEPER_LISTS)",
    )
    common.add_argument(
        "--data-dir",
        metavar="DIR",
        default=argparse.SUPPRESS,
        help="where the data is written, and the last run read from "
        "(NIXKEEPER_DATA_DIR)",
    )
    common.add_argument(
        "--notify",
        choices=["none", *notify.SENDERS],
        default=argparse.SUPPRESS,
        help="how to report what changed (NIXKEEPER_NOTIFY; default: none)",
    )
    p = argparse.ArgumentParser(
        prog="nixkeeper",
        description="Health dashboard for the nixpkgs packages you maintain: "
        "new releases, build and update failures, and vulnerabilities.",
        parents=[common],
    )
    p.add_argument("--version", action="version", version=f"nixkeeper {version()}")
    sub = p.add_subparsers(dest="command", metavar="COMMAND")
    for name, (what, _) in COMMANDS.items():
        command = sub.add_parser(
            name,
            help=what,
            description=f"{what[0].upper()}{what[1:]}.",
            parents=[common],
        )
        if name == "sync":
            command.add_argument(
                "--all-packages",
                action="store_true",
                default=None,
                help="track every nixpkgs package, not only the lists' "
                "(NIXKEEPER_ALL_PACKAGES): the community instance's mode",
            )
            command.add_argument(
                "--if-older",
                metavar="HOURS",
                type=float,
                help="only if the last sync is older than this (or there's none): "
                "for catching up at login or boot without syncing again",
            )
    sub.add_parser(
        "paths",
        help="where the lists and data are, and which setting says so",
        description="Where the lists and data are, and which setting says so.",
        parents=[common],
    )
    check = sub.add_parser(
        "community-check",
        help="try the community rules for real (all, or those named)",
        description="Run the community update checks (community/update-checks.nix) "
        "for real, against nixpkgs' current versions, and say which community "
        "ignore rules (community/ignored-updates.nix) and up-to-date rules "
        "(community/up-to-date.nix) no longer do anything: every rule, or those "
        "named. Fails if an update check finds nothing. GitHub "
        "rules need a token (GITHUB_TOKEN, or a gh login).",
        parents=[common],
    )
    check.add_argument("names", metavar="NAME", nargs="*", help="a package's rule")
    check.add_argument(
        "--file", metavar="PATH", help="another community file (default: nixkeeper's)"
    )
    check.add_argument(
        "--changed-from",
        metavar="DIR",
        help="only the rules added or changed since this version of community/ "
        "(for a pull request); a new ignore rule must match the bot's latest "
        "failed attempt, and a new up-to-date rule what Repology shows",
    )
    check.add_argument(
        "--report-issue",
        action="store_true",
        help="keep the repository's community checks status issue up to date "
        "instead of failing on broken rules (needs a token: GITHUB_TOKEN)",
    )
    init = sub.add_parser(
        "init",
        help="start your package lists (where --lists says, else the default)",
        description="Start your package lists: a folder of Nix files to edit, "
        "where --lists (or NIXKEEPER_LISTS) says, else the default.",
        parents=[common],
    )
    init.add_argument(
        "--maintainer",
        metavar="HANDLE",
        action="append",
        default=[],
        help="a GitHub handle whose nixpkgs packages to track (repeatable)",
    )
    write = sub.add_parser(
        "page",
        help="write the page and the data into a folder, ready for any static host",
        description="Write the page and a copy of the data into DIR (created "
        "if needed; only an empty folder or an earlier page), ready for any "
        "static host. Run it again after a sync.",
        parents=[common],
    )
    write.add_argument("dir", metavar="DIR", help="the folder to write")
    serve = sub.add_parser(
        "serve",
        help="show the page on this computer, with the data as it is",
        description="Serve the page and the data, as they are (a new sync "
        "shows on the next reload), until Ctrl+C.",
        parents=[common],
    )
    serve.add_argument(
        "--port", type=int, default=8000, help="the port to listen on (default: 8000)"
    )
    serve.add_argument(
        "--bind",
        metavar="ADDRESS",
        default="127.0.0.1",
        help="the address to listen on (default: 127.0.0.1, this computer only)",
    )
    return p


def settings(args):
    """Work out each setting, and where it came from.

    The flag wins, then the environment, then the default.

    Returns:
        {flag: (value, where it came from)}.
    """
    found = {}
    for flag, (name, env) in SETTINGS.items():
        if getattr(args, flag, None):
            found[flag] = (getattr(args, flag), f"--{flag.replace('_', '-')}")
        elif os.environ.get(env):
            found[flag] = (os.environ[env], env)
        else:
            found[flag] = (config.DEFAULTS[name], "default")
    return found


def paths(found):
    """Print where the lists, the data and the page are, and the notification method.

    Each line also says which setting gives it.
    """
    for flag, label in (("lists", "lists"), ("data_dir", "data"), ("notify", "notify")):
        value, source = found[flag]
        if flag == "notify":
            print(f"{label + ':':7} {value}  ({source})")
            continue
        where = os.path.abspath(value)
        missing = "" if os.path.exists(where) else ", missing"
        print(f"{label + ':':7} {where}  ({source}{missing})")
    try:
        print(f"{'page:':7} {page.page_dir()}  (shipped with nixkeeper)")
    except SystemExit:
        print(f"{'page:':7} not included in this copy of nixkeeper")


def main(argv=None):
    """Run the command argv gives (sys.argv's by default)."""
    args = parser().parse_args(argv)
    if not args.command:
        parser().print_help(sys.stderr)
        sys.exit(2)
    found = settings(args)
    for flag, (name, _) in SETTINGS.items():
        setattr(config, name, found[flag][0])
    if args.command == "paths":
        paths(found)
        return
    if args.command == "init":
        folder = os.path.abspath(found["lists"][0])
        init.write(folder, args.maintainer)
        print(f"Wrote your package lists to {folder}.")
        if not args.maintainer:
            print("Add your GitHub handle to maintainers in default.nix.")
        print(
            "Next: `nixkeeper sync` writes the data to "
            f"{os.path.abspath(found['data_dir'][0])}."
        )
        return
    if args.command == "community-check":
        # Every rule of every kind; or, named, each kind a name has a rule of.
        checks = ignored = None
        unknown = []
        if args.names:
            checks, ignored, unknown = community.sort_names(args.names, args.file)
        if args.changed_from:
            checks, ignored = community.changed(args.changed_from)
            if not checks and not ignored:
                print("No community rules added or changed.", file=sys.stderr)
                return
        results = community.run(checks, args.file)
        stale = community.stale_ignores(ignored) if ignored != [] else {}
        stale_up = community.stale_up_to_date(ignored) if ignored != [] else {}
        failed = community.report(results, stale, stale_up)
        for kind, have, gone in (
            ("ignore rules", community.ignores(), stale),
            ("up-to-date rules", community.up_to_date(), stale_up),
        ):
            still = [n for n in ignored or [] if n in have and n not in gone]
            if still:
                print(f"  {kind} for {', '.join(still)}: still apply")
        for name in unknown:  # a typo, most likely
            print(f"  {name}: no community rule of that name")
        failed += len(unknown)
        if args.report_issue:
            community.publish(results, stale, stale_up)
            return
        # A pull request's ignore or up-to-date rule has to do something when
        # it's added.
        if args.changed_from:
            failed += sum(map(len, stale.values())) + len(stale_up)
        if failed:
            sys.exit(f"{failed} community rule(s) don't work.")
        return
    if args.command == "page":
        with lock.held():  # not mid-sync: the data is swapped in whole
            folder = page.write(args.dir)
        print(f"Wrote the page and the data to {folder}: host that folder as is.")
        return
    if args.command == "serve":
        page.serve(args.port, args.bind)
        return
    if getattr(args, "all_packages", None):
        config.ALL_PACKAGES = True
    with lock.held():
        if getattr(args, "if_older", None) is not None:
            age = last_sync_age()
            if age is not None and age < args.if_older:
                print(
                    f"The last sync was {age:.1f} hours ago (under {args.if_older:g}): "
                    "nothing to do.",
                    file=sys.stderr,
                )
                return
        importlib.import_module(COMMANDS[args.command][1]).main()


def last_sync_age():
    """Return the hours since the last sync finished, or None if there was none."""
    checked = history.load_previous_run().get("checkedAt")
    if not checked:
        return None
    return (datetime.now(UTC) - datetime.fromisoformat(checked)).total_seconds() / 3600


def _alias(command):
    """Make an old command's entry point: it says the new name, then runs it."""

    def run():
        """Run the command under its new name."""
        print(
            f"nixkeeper-{command} is now `nixkeeper {command}`; the old name "
            "works until 1.0.",
            file=sys.stderr,
        )
        main([command, *sys.argv[1:]])

    return run


# The old commands (pyproject.toml's [project.scripts]).
sync_alias = _alias("sync")
frequent_check_alias = _alias("frequent-check")
pr_check_alias = _alias("pr-check")
