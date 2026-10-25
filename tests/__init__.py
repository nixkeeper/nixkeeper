"""Offline tests for nixkeeper: Repology, GitHub and the nixpkgs index are
replaced by small hand-written samples (tests/helpers.py).

Run with `nix flake check`, or from the repository root inside `nix develop`:
    python3 -m unittest discover -s tests -t .
"""

import os

from nixkeeper import config


def offline():
    """Tests never reach the real sites: each source's address off, unless a
    test gives its own. Again after a test reloads config (test_settings.py),
    which brings back the real addresses."""
    # Fake sites answer at once: no waiting between their pages (http.pace), but
    # for tests of the pause itself (test_http.py).
    config.SITE_PAUSE_SECONDS = 0
    # No nixkeeper-hydra digest: tests of the Hydra step ask (fake) Hydra about
    # each job, as before, unless they give a digest of their own
    # (test_hydra_digest.py).
    config.HYDRA_DIGEST_URL = ""
    # Nor a nixkeeper-versions digest: Repology is asked about each package.
    config.VERSIONS_DIGEST_URL = ""
    # Nor a nixkeeper-updates digest: the bot's logs are read per package.
    config.UPDATES_DIGEST_URL = ""
    # Nor a nixkeeper-vulnerabilities digest: Repology's flag decides; nor the
    # newest release's package index (tests give their own versions).
    config.VULNERABILITIES_DIGEST_URL = ""
    config.STABLE_INDEX_URL = ""
    # Nor a nixkeeper-prs digest: the sync lists PRs and issues itself.
    config.PRS_DIGEST_URL = ""
    # Not on GitHub Actions, wherever the tests run: the log's plain form
    # (log.py). A test of GitHub's form patches it on.
    os.environ.pop("GITHUB_ACTIONS", None)


offline()
