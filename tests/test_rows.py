import unittest

from nixkeeper import rows as rows_module
from nixkeeper.rows import (
    add_source_links,
    build_rows,
    channel_versions,
    search_term,
    source_url,
)
from nixkeeper.sources import nixpkgs as nixpkgs_source
from tests.helpers import NIXPKGS, nix, other, pkg, project


class Rows(unittest.TestCase):
    def rows(self, *projects):
        return build_rows({p["project"] or p["name"]: p for p in projects}, NIXPKGS)

    WESNOTH = [
        nix("wesnoth", "1.18.8", "newest"),
        nix("wesnoth-devel", "1.19.24", "devel"),
        other("debian", "1.18.8", "newest"),
        other("arch", "1.19.24", "devel"),
    ]

    def test_different_versions_split_into_rows(self):
        stable, devel = self.rows(
            project("wesnoth", ["wesnoth", "wesnoth-devel"], self.WESNOTH, "wesnoth")
        )
        self.assertEqual(
            (stable["name"], stable["nixVersion"], stable["devel"]),
            ("wesnoth", "1.18.8", False),
        )
        self.assertEqual(
            (devel["name"], devel["nixVersion"], devel["devel"]),
            ("wesnoth-devel", "1.19.24", True),
        )

    def test_kept_only_beside_a_beta_is_the_main_line(self):
        # firefox, 2026-10-15: Repology called 157.0.1 legacy because nixpkgs
        # also has firefox-devedition 158.0b1; 158.0 was out.
        entries = [
            nix("firefox", "157.0.1", "legacy"),
            nix("firefox-devedition", "158.0b1", "outdated"),
            other("arch", "158.0", "newest"),
            other("arch", "159.0b2", "devel"),
        ]
        rows = {
            r["name"]: r
            for r in self.rows(
                project(
                    "firefox", ["firefox", "firefox-devedition"], entries, "firefox"
                )
            )
        }
        firefox = rows["firefox"]
        # And firefox-esr, kept beside the release, not the beta.
        esr_entries = [
            nix("firefox-esr", "153.4.0", "legacy") | {"vulnerable": True},
            nix("firefox", "158.0", "newest"),
            nix("firefox-devedition", "159.0b1", "devel"),
            other("arch", "158.0", "newest"),
        ]
        esr = {
            r["name"]: r
            for r in self.rows(
                project(
                    "firefox",
                    ["firefox-esr", "firefox", "firefox-devedition"],
                    esr_entries,
                    "firefox",
                )
            )
        }["firefox-esr"]
        self.assertEqual(esr["keptBeside"], {"attr": "firefox", "version": "158.0"})
        # Repology's flag, by the newer series' CVE ranges: not for it.
        self.assertNotIn("nixVulnerable", esr)
        self.assertEqual(
            (firefox["nixStatus"], firefox["refVersion"], firefox["devel"]),
            ("outdated", "158.0", False),
        )
        self.assertNotIn("keptBeside", firefox)
        # Beside a newer stable release (gnumake42 beside gnumake): still kept.
        kept = [
            nix("gnumake42", "4.2.1", "legacy"),
            nix("gnumake", "4.4.1", "newest"),
            other("arch", "4.4.1", "newest"),
        ]
        rows = {
            r["name"]: r
            for r in self.rows(
                project("gnumake", ["gnumake42", "gnumake"], kept, "gnumake")
            )
        }
        self.assertEqual(rows["gnumake42"]["nixStatus"], "legacy")
        # Beside a release named "-stable" (godot_4_5 beside godot
        # 4.7.2-stable, 2026-10-15): a release, not a beta; still kept.
        godot = [
            nix("godot_4_5", "4.5.1-stable", "legacy"),
            nix("godot", "4.7.2-stable", "outdated"),
            other("arch", "4.7.2", "newest"),
        ]
        rows = {
            r["name"]: r
            for r in self.rows(project("godot", ["godot_4_5", "godot"], godot, "godot"))
        }
        self.assertEqual(rows["godot_4_5"]["nixStatus"], "legacy")
        self.assertEqual(
            rows["godot_4_5"]["keptBeside"],
            {"attr": "godot", "version": "4.7.2-stable"},
        )

    def test_outdated_only_by_a_release_word(self):
        """godot, 2026-10-15: 4.7.2-stable, which Repology ranks below 4.7.2."""
        entries = [
            nix("godot", "4.7.2-stable", "outdated"),
            other("arch", "4.7.2", "newest"),
        ]
        (row,) = self.rows(project("godot", ["godot"], entries, "godot"))
        self.assertEqual(row["nixStatus"], "newest")
        # Behind by more than the word: still outdated.
        entries[0] = nix("godot", "4.7.1-stable", "outdated")
        (row,) = self.rows(project("godot", ["godot"], entries, "godot"))
        self.assertEqual((row["nixStatus"], row["refVersion"]), ("outdated", "4.7.2"))
        # Nor ahead: Repology's rules have their reasons (xcircuit).
        entries[0] = nix("godot", "4.8-stable", "outdated")
        (row,) = self.rows(project("godot", ["godot"], entries, "godot"))
        self.assertEqual(row["nixStatus"], "outdated")

    def test_behind_only_nixpkgs_old_channels(self):
        """python3Packages.azure-eventhub, 2026-10-20: 5.15.1, PyPI's too;
        25.11 had 39.0.0, a mistake since reverted."""

        def row(*others):
            entries = [nix("p", "5.15.1", "outdated"), *others]
            (row,) = self.rows(project("p", ["p"], entries, "p"))
            return row["nixStatus"], row["refVersion"]

        old = other("nix_stable_25_11", "39.0.0", "newest")
        current = other("nix_stable_26_05", "5.15.1", "outdated")
        pypi = other("pypi", "5.15.1", "outdated")
        self.assertEqual(row(old, current, pypi), ("newest", "5.15.1"))
        # Nobody else packages it: the newest still, as 26.05 has it too.
        self.assertEqual(row(old, current), ("newest", "5.15.1"))
        # Someone else has a newer one: outdated against that.
        newer = other("pypi", "5.16.0", "outdated")
        self.assertEqual(row(old, current, newer), ("outdated", "5.16.0"))
        # The newest channel can be ahead for real (a backport, msedgedriver).
        ahead = other("nix_stable_26_05", "39.0.0", "newest")
        self.assertEqual(row(ahead), ("outdated", "39.0.0"))
        # Unless an upstream index has nixpkgs' version: it says what's out.
        self.assertEqual(row(ahead, pypi), ("newest", "5.15.1"))
        self.assertEqual(
            row(ahead, other("pypi", "5.15.0", "outdated")), ("outdated", "39.0.0")
        )
        # Or another distribution has it too: a release.
        self.assertEqual(
            row(old, current, other("aur", "39.0.0", "newest")), ("outdated", "39.0.0")
        )

    def test_only_nixpkgs(self):
        """python313Packages.pbar2, 2026-10-23: unique, as no repository
        outside nixpkgs has it (its release channels aren't another)."""
        entries = [
            nix("p", "2.2.1", "unique"),
            other("nix_stable_26_05", "2.2.1", "unique"),
        ]
        (row,) = self.rows(project("p", ["p"], entries, "p"))
        self.assertTrue(row.get("onlyNixpkgs"))
        entries.append(other("aur", "2.2.1", "newest"))
        (row,) = self.rows(project("p", ["p"], entries, "p"))
        self.assertNotIn("onlyNixpkgs", row)

    def test_behind_only_another_commit(self):
        """vimPlugins.nvim-treesitter-parsers.liquid, 2026-10-20:
        0.0.0+rev=e45dbac, 26.05's 0.0.0+rev=9566ca7, ranked as letters."""

        def row(*others):
            entries = [nix("p", "0.0.0+rev=e45dbac", "outdated"), *others]
            (row,) = self.rows(project("p", ["p"], entries, "p"))
            return row["nixStatus"], row["refVersion"]

        stable = other("nix_stable_26_05", "0.0.0+rev=9566ca7", "unique")
        self.assertEqual(row(stable), ("newest", "0.0.0+rev=e45dbac"))
        # Another distribution has that commit: kept.
        aur = other("aur", "0.0.0+rev=9566ca7", "newest")
        self.assertEqual(row(stable, aur), ("outdated", "0.0.0+rev=9566ca7"))
        # A newer version, not only another commit: kept.
        newer = other("nix_stable_26_05", "0.1.0+rev=9566ca7", "unique")
        self.assertEqual(row(newer), ("outdated", "0.1.0+rev=9566ca7"))

    def test_unsupported(self):
        """cudaPackages.cuda_compat, 2026-10-20: 0-unsupported, nixpkgs'
        version for what it doesn't build by default."""
        entries = [
            nix("p", "0-unsupported", "outdated"),
            other("nix_stable_26_05", "12.9.40580548", "unique"),
        ]
        (row,) = self.rows(project("p", ["p"], entries, "p"))
        self.assertEqual((row["nixStatus"], row["refVersion"]), ("unsupported", None))

    def test_outdated_only_by_a_snapshots_spelling(self):
        """gawkextlib.csv, 2026-10-20: unstable-2022-10-20, against nixpkgs'
        older channels' 2022-10-20."""

        def row(nix_version, newest):
            entries = [
                nix("p", nix_version, "outdated"),
                other("nix_stable_25_05", newest, "unique"),
            ]
            (row,) = self.rows(project("p", ["p"], entries, "p"))
            return row["nixStatus"], row["refVersion"]

        self.assertEqual(row("unstable-2022-10-20", "2022-10-20")[0], "newest")
        self.assertEqual(row("0-unstable-2012-12-08", "2012-12-08")[0], "newest")
        # A newer date, or a release, is still newer.
        self.assertEqual(
            row("unstable-2022-10-20", "2023-01-01"), ("outdated", "2023-01-01")
        )
        self.assertEqual(row("1.2-unstable-2022-10-20", "2022-10-20")[0], "outdated")

    def test_outdated_only_by_a_distributions_snapshot(self):
        """python3Packages.mintotp 0.3.0, 2026-10-15: SlackBuilds' git
        snapshot 0.3.0.20240120 was the only newer version."""

        def status(nix_version, newest, *repos):
            entries = [
                nix("p", nix_version, "outdated"),
                *(other(r, newest, "newest") for r in repos),
            ]
            (row,) = self.rows(project("p", ["p"], entries, "p"))
            return row["nixStatus"]

        cases = {
            # One distribution's snapshot: the newest.
            ("0.3.0", "0.3.0.20240120", ("slackbuilds",)): "newest",
            ("1.2.0", "1.2.0+20251126", ("void_x86_64",)): "newest",
            ("1.04", "1.04-20190106", ("gnuguix",)): "newest",
            ("2.1", "2.1-git20240301.abc1234", ("aur",)): "newest",
            # One distribution under several names is still one.
            ("0.3.0", "0.3.0.20240120", ("debian_13", "debian_unstable")): "newest",
            # On an upstream index: a release (iso4217).
            ("1.16", "1.16.20260101", ("pypi",)): "outdated",
            ("5.6.3.6", "5.6.3.6.20240818", ("pypi", "macports")): "outdated",
            # In several distributions (fcitx5-pinyin-zhwiki).
            ("0.3.0", "0.3.0.20260416", ("arch", "debian_13")): "outdated",
            # Not only a date added: a newer release.
            ("0.3.0", "0.3.1", ("slackbuilds",)): "outdated",
            ("0.3.0", "0.3.0.1", ("slackbuilds",)): "outdated",
            ("0.3.0", "0.4.0.20240120", ("slackbuilds",)): "outdated",
        }
        for (version, newest, repos), expected in cases.items():
            with self.subTest(newest=newest, repos=repos):
                self.assertEqual(status(version, newest, *repos), expected)

    def test_newest_not_a_packaging_of_it(self):
        """curl, 2026-10-16: Baulk's 8.23.0.1 is its packaging of 8.23.0,
        which 29 distributions have."""

        def ref(nix_version, *entries):
            rows = self.rows(
                project(
                    "curl",
                    ["curl"],
                    [nix("curl", nix_version, "outdated"), *entries],
                    "curl",
                )
            )
            return rows[0]["refVersion"]

        newest = [other(r, "8.23.0", "newest") for r in ("arch", "debian_14", "fedora")]
        self.assertEqual(
            ref("8.22.0", *newest, other("baulk", "8.23.0.1", "newest")), "8.23.0"
        )
        # rakudo's "_01", the same.
        self.assertEqual(
            ref("8.22.0", *newest, other("aur", "8.23.0_01", "newest")), "8.23.0"
        )
        # In as many distributions as the shorter one: a release, not a packaging.
        self.assertEqual(
            ref(
                "8.22.0",
                other("arch", "8.23.0", "newest"),
                other("baulk", "8.23.0.1", "newest"),
            ),
            "8.23.0",
        )
        self.assertEqual(
            ref(
                "8.22.0",
                other("arch", "8.23.0", "newest"),
                *(other(r, "8.23.0.1", "newest") for r in ("baulk", "fedora")),
            ),
            "8.23.0.1",
        )
        # nixpkgs at 8.23.0 and Repology saying behind: the added part may be a
        # real release, first in one distribution. Kept.
        self.assertEqual(
            ref("8.23.0", *newest, other("baulk", "8.23.0.1", "newest")), "8.23.0.1"
        )

    def test_an_older_series_compared_within_it(self):
        # python313 beside python315, 2026-10-15: behind in 3.13, not 3.15.
        entries = [
            nix("python313", "3.13.15", "outdated"),
            nix("python315", "3.15.0", "newest"),
            other("arch", "3.15.0", "newest"),
            other("debian", "3.13.16", "legacy"),
            other("fedora", "3.13.9999", "rolling"),
            other("aur", "3.13.17rc1", "outdated"),
        ]
        rows = {
            r["name"]: r
            for r in self.rows(
                project("python", ["python313", "python315"], entries, "python")
            )
        }
        self.assertEqual(rows["python313"]["refVersion"], "3.13.16")
        self.assertEqual(rows["python313"]["nixStatus"], "outdated")
        self.assertEqual(rows["python315"]["refVersion"], "3.15.0")
        # Nothing newer known in its series: Repology's verdict as it is.
        entries[3] = other("debian", "3.13.15", "legacy")
        rows = {
            r["name"]: r
            for r in self.rows(
                project("python", ["python313", "python315"], entries, "python")
            )
        }
        self.assertEqual(rows["python313"]["refVersion"], "3.15.0")

    def kept(self, name, version, newer, *others):
        """name's row, kept at version beside newer, with others' entries."""
        entries = [
            nix(name, version, "legacy"),
            nix("main", newer, "newest"),
            other("arch", newer, "newest"),
            *others,
        ]
        rows = self.rows(project("p", [name, "main"], entries, "p"))
        return next(r for r in rows if r["name"] == name)

    def test_a_kept_series_behind_in_it(self):
        # glibmm_2_4 2.66.8 beside glibmm 2.88.0, 2026-10-15: 2.66.10 out.
        row = self.kept(
            "glibmm_2_4",
            "2.66.8",
            "2.88.0",
            other("debian_13", "2.66.10", "legacy"),
            other("alpine_edge", "2.66.10", "legacy"),
        )
        self.assertEqual(
            (row["nixStatus"], row["refVersion"], row["keptBeside"]["version"]),
            ("outdated", "2.66.10", "2.88.0"),
        )
        # Once the channel has it: kept again.
        channel_versions([row], {"glibmm_2_4": pkg("glibmm_2_4", version="2.66.10")})
        self.assertEqual(row["nixStatus"], "legacy")

    def test_a_kept_series_beside_its_own_binary(self):
        # thunderbird-153 153.4.0 beside thunderbird 158.0, 2026-10-23:
        # nixpkgs' thunderbird-esr-bin had 153.5.0, which made its series
        # 153.4; 153.5.1 was out.
        row = self.kept(
            "thunderbird-153",
            "153.4.0",
            "158.0",
            nix("thunderbird-esr-bin", "153.5.0", "outdated"),
            other("freebsd", "153.5.1", "legacy"),
            other("gentoo", "153.5.1", "legacy"),
        )
        self.assertEqual(
            (row["nixStatus"], row["refVersion"], row["keptBeside"]["version"]),
            ("outdated", "153.5.1", "158.0"),
        )

    def test_a_kept_series_not_by_its_packaging(self):
        # ruby 3.4.9, 2026-10-15: 3.4.11 in five distributions, Chocolatey's
        # and Liguros' 3.4.11.1 in two.
        row = self.kept(
            "ruby_3_4",
            "3.4.9",
            "4.0.7",
            *(other(r, "3.4.11", "legacy") for r in ("homebrew", "macports", "void")),
            *(other(r, "3.4.11.1", "legacy") for r in ("chocolatey", "liguros")),
        )
        self.assertEqual((row["nixStatus"], row["refVersion"]), ("outdated", "3.4.11"))
        # But a newer one, or one in more distributions, is taken.
        row = self.kept(
            "ruby_3_4",
            "3.4.9",
            "4.0.7",
            *(other(r, "3.4.11", "legacy") for r in ("homebrew", "macports")),
            *(other(r, "3.4.12", "legacy") for r in ("arch", "fedora")),
        )
        self.assertEqual(row["refVersion"], "3.4.12")

    def test_a_kept_series_needs_good_evidence(self):
        cases = {
            # One distribution only (debian_13 and debian_unstable are one).
            "one": (
                "glibmm_2_4",
                "2.66.8",
                "2.88.0",
                "2.66.10",
                ["debian_13", "debian_unstable"],
            ),
            # Only adding a part (deepin's 2.69.1) or a revision (1.91.0-1).
            "part": ("autoconf269", "2.69.5", "2.72", "2.69.5.1", ["deepin", "fedora"]),
            "revision": ("boost", "1.91.0", "1.92.0", "1.91.0-1", ["xrepo", "fedora"]),
            # The attribute names the whole version.
            "pinned": ("sbcl_2_4_6", "2.4.6", "2.6.0", "2.4.11", ["alpine", "fedora"]),
            # Another numbering, and the next major's previews.
            "numbering": (
                "zulu17",
                "17.0.19",
                "21.0.11",
                "17.68.203",
                ["macports", "aur"],
            ),
            "previews": ("gimp2", "2.10.38", "3.2.0", "2.99.10", ["mageia", "fedora"]),
            # Not in version's shape (jdk8 8u504-b01, 8.452.09 elsewhere).
            "shape": ("jdk8", "8u504-b01", "21.0.11", "8.452.09", ["pisi", "fedora"]),
            # A series named by its major, of three parts: major.minor (linux
            # 6.18 beside 7.2; 6.19 is another series).
            "wide": ("linux", "6.18.56", "7.2.10", "6.19.14", ["alpine", "fedora"]),
            # A snapshot.
            "snapshot": (
                "fm",
                "0-unstable-2024-01-03",
                "1.0",
                "0.99",
                ["aur", "fedora"],
            ),
        }
        for case, (name, version, newer, found, repos) in cases.items():
            with self.subTest(case):
                row = self.kept(
                    name, version, newer, *(other(r, found, "legacy") for r in repos)
                )
                self.assertEqual(row["nixStatus"], "legacy")

    def test_kept_series_only_none_devel(self):
        # coq's project once its current version moved to rocq: every
        # series nixpkgs keeps is legacy. The newest is the stable one, not
        # the shortest name (coq_8_7), so none is a devel variant behind.
        entries = [
            nix("coq_8_7", "8.7.2", "legacy"),
            nix("coq_8_10", "8.10.2", "legacy"),
            nix("coq_8_20", "8.20.1", "legacy"),
            other("arch", "9.3.0", "newest"),
        ]
        found = self.rows(
            project("coq", ["coq_8_7", "coq_8_10", "coq_8_20"], entries, "coq")
        )
        self.assertEqual(
            {r["name"]: r["devel"] for r in found},
            {"coq_8_7": False, "coq_8_10": False, "coq_8_20": False},
        )

    def test_repo_count_counts_repositories(self):
        # A repository listing the package twice (two subpackages) counts once.
        (row,) = self.rows(
            project(
                "unciv",
                ["unciv"],
                [
                    nix("unciv", "4.22.1", "outdated"),
                    other("debian", "4.22.6", "newest"),
                    other("debian", "4.22.6", "newest"),
                    other("arch", "4.22.6", "newest"),
                ],
                "unciv",
            )
        )
        self.assertEqual(row["repoCount"], 2)

    def test_devel_row_compares_against_devel_versions(self):
        stable, devel = self.rows(
            project("wesnoth", ["wesnoth", "wesnoth-devel"], self.WESNOTH, "wesnoth")
        )
        self.assertEqual(stable["refVersion"], "1.18.8")
        self.assertEqual(devel["refVersion"], "1.19.24")

    def test_untracked_variant_is_ignored(self):
        [row] = self.rows(project("wesnoth", ["wesnoth"], self.WESNOTH, "wesnoth"))
        self.assertEqual(
            (row["name"], row["nixVersion"], row["devel"]), ("wesnoth", "1.18.8", False)
        )

    def test_same_version_variants_stay_one_row(self):
        entries = [
            nix("heroic", "2.22.3", "newest"),
            nix("heroic-unwrapped", "2.22.3", "newest"),
        ]
        [row] = self.rows(
            project(
                "heroic-unwrapped",
                ["heroic-unwrapped", "heroic"],
                entries,
                "heroic-games-launcher",
            )
        )
        self.assertEqual(row["name"], "heroic")  # first attr alphabetically
        self.assertEqual(row["attrs"], ["heroic", "heroic-unwrapped"])
        self.assertEqual(row["project"], "heroic-games-launcher")

    def test_variants_sharing_a_pname_are_named_by_attribute(self):
        entries = [
            nix("_1password-gui", "8.12.36", "newest"),
            nix("_1password-gui-beta", "8.12.32-26.BETA", "legacy"),
            other("aur", "8.12.36", "newest"),
            other("aur", "8.12.38_25.BETA", "ignored"),
        ]
        stable, beta = self.rows(
            project(
                "_1password-gui",
                ["_1password-gui", "_1password-gui-beta"],
                entries,
                "1password",
            )
        )
        self.assertEqual(
            (stable["name"], stable["searchTerm"]), ("_1password-gui", "_1password-gui")
        )
        self.assertEqual(
            (beta["name"], beta["searchTerm"]),
            ("_1password-gui-beta", "_1password-gui-beta"),
        )
        self.assertEqual((beta["nixStatus"], beta["devel"]), ("legacy", True))
        # No devel version elsewhere (the aur beta is "ignored"): falls back to stable.
        self.assertEqual(beta["refVersion"], "8.12.36")

    def test_an_older_series_split_off_isnt_devel(self):
        entries = [
            nix("gnumake", "4.4.1", "newest"),
            nix("gnumake42", "4.2.1", "legacy"),
            other("arch", "4.4.1", "newest"),
        ]
        stable, older = self.rows(
            project("gnumake", ["gnumake", "gnumake42"], entries, "gnumake")
        )
        self.assertEqual((stable["name"], stable["devel"]), ("gnumake", False))
        self.assertEqual((older["name"], older["devel"]), ("gnumake42", False))
        self.assertEqual(older["keptBeside"], {"attr": "gnumake", "version": "4.4.1"})

    def test_repology_devel_status_marks_single_row_devel(self):
        [row] = self.rows(
            project(
                "lincity", ["lincity"], [nix("lincity", "1.13.1", "devel")], "lincity"
            )
        )
        self.assertTrue(row["devel"])

    def test_nested_package_uses_its_own_nix_entry(self):
        entries = [
            nix("pandoc", "3.8", "newest"),
            nix("haskellPackages.pandoc", "3.7.0.2", "legacy"),
        ]
        [row] = self.rows(
            project(
                "haskellPackages.pandoc", ["haskellPackages.pandoc"], entries, "pandoc"
            )
        )
        self.assertEqual(
            (row["name"], row["nixVersion"], row["nixStatus"]),
            ("haskellPackages.pandoc", "3.7.0.2", "legacy"),
        )
        # Kept beside the newer one, which the page names.
        self.assertEqual(row["keptBeside"], {"attr": "pandoc", "version": "3.8"})

    def test_kept_beside_the_plainest_name_of_the_newest(self):
        entries = [
            nix("tracy", "0.14.1", "newest"),
            nix("tracy_0_14", "0.14.1", "newest"),
            nix("tracy_0_13", "0.13.1", "legacy"),
            nix("tracy_0_11", "0.11.1", "legacy"),
        ]
        [row] = self.rows(project("tracy_0_11", ["tracy_0_11"], entries, "tracy"))
        self.assertEqual(row["keptBeside"], {"attr": "tracy", "version": "0.14.1"})
        [newest] = self.rows(project("tracy", ["tracy"], entries, "tracy"))
        self.assertNotIn("keptBeside", newest)

    def test_not_in_nixpkgs(self):
        [row] = self.rows(project("python3Packages.requests", [], []))
        self.assertEqual(row["name"], "python3Packages.requests")
        self.assertEqual(
            (row["nixStatus"], row["nixVersion"], row["project"]),
            ("missing", None, None),
        )
        self.assertNotIn("platforms", row)  # not "any platform"
        self.assertNotIn("homepage", row)
        self.assertNotIn("maintainers", row)  # unknown, not none

    def test_in_nixpkgs_but_repology_lists_other_repositories_only(self):
        # keeperrl: Repology has a project of that name (other repositories'
        # packages), but not nixpkgs' (its version "alpha34" it can't read).
        nixpkgs = {
            "keeperrl": {**pkg("keeperrl", ["x86_64-linux"]), "version": "alpha34"}
        }
        [row] = build_rows(
            {
                "keeperrl": project(
                    "keeperrl",
                    ["keeperrl"],
                    [other("openbsd", "1.3", "newest")],
                    "keeperrl",
                )
            },
            nixpkgs,
        )
        self.assertEqual((row["nixStatus"], row["nixVersion"]), ("unlisted", "alpha34"))

    def test_platforms(self):
        def plat(attr):
            [row] = self.rows(project(attr, [attr], [nix(attr, "1", "newest")], attr))
            return row["platforms"]

        self.assertEqual(plat("wesnoth"), {"linux": True, "darwin": True})
        self.assertEqual(plat("heroic"), {"linux": True, "darwin": False})
        self.assertEqual(plat("bbedit"), {"linux": False, "darwin": True})
        self.assertIsNone(plat("fzssh"))  # nothing declared: unrestricted
        self.assertEqual(
            plat("odd"),  # pattern entries ignored
            {"linux": True, "darwin": False, "systems": ["x86_64-linux"]},
        )

    def test_platforms_by_system(self):
        def plat(platforms, bad=None):
            meta = {"platforms": platforms}
            if bad:
                meta["badPlatforms"] = bad
            return nixpkgs_source.platforms([{"meta": meta}])

        every = ["x86_64-linux", "aarch64-linux", "aarch64-darwin"]
        self.assertEqual(plat(every), {"linux": True, "darwin": True})
        # A Linux system missing: which ones, then.
        self.assertEqual(
            plat(["x86_64-linux", "aarch64-darwin"]),
            {
                "linux": True,
                "darwin": True,
                "systems": ["aarch64-darwin", "x86_64-linux"],
            },
        )
        self.assertEqual(
            plat(["aarch64-linux"]),
            {"linux": True, "darwin": False, "systems": ["aarch64-linux"]},
        )
        # meta.badPlatforms takes systems away.
        self.assertEqual(
            plat(every, bad=["aarch64-linux"]),
            {
                "linux": True,
                "darwin": True,
                "systems": ["aarch64-darwin", "x86_64-linux"],
            },
        )
        self.assertEqual(
            plat(every, bad=["aarch64-darwin"]), {"linux": True, "darwin": False}
        )
        # Only x86_64-darwin, which nixpkgs no longer builds: Darwin, but none
        # of the systems it builds.
        self.assertEqual(
            plat(["x86_64-darwin"]), {"linux": False, "darwin": True, "systems": []}
        )

    def test_homepage_takes_first_of_a_list(self):
        [row] = self.rows(
            project(
                "heroic",
                ["heroic"],
                [nix("heroic", "1", "newest")],
                "heroic-games-launcher",
            )
        )
        self.assertEqual(row["homepage"], "https://heroic.example")

    def test_maintainers_of_all_attributes_once(self):
        nixpkgs = {
            "heroic": pkg("heroic", maintainers=["iedame", "TomaSajt"]),
            "heroic-unwrapped": pkg("heroic", maintainers=["tomasajt", "aidalgol"]),
            "orphan": pkg("orphan"),
        }
        nixpkgs["heroic"]["meta"]["maintainers"].append({"name": "No Handle"})
        entries = [nix("heroic", "1", "newest"), nix("orphan", "1", "newest")]
        heroic, orphan = build_rows(
            {
                "heroic": project(
                    "heroic", ["heroic", "heroic-unwrapped"], entries[:1]
                ),
                "orphan": project("orphan", ["orphan"], entries[1:]),
            },
            nixpkgs,
        )
        self.assertEqual(heroic["maintainers"], ["iedame", "TomaSajt", "aidalgol"])
        self.assertEqual(orphan["maintainers"], [])  # none: searchable as @none

    def test_named_after_a_top_level_attribute(self):
        entries = [
            nix("azure-sdk-for-cpp.cmake", "4", "newest"),
            nix("cmake", "4", "newest"),
        ]
        nixpkgs = {"cmake": pkg("cmake"), "azure-sdk-for-cpp.cmake": pkg("cmake")}
        (row,) = build_rows(
            {"cmake": project("cmake", ["azure-sdk-for-cpp.cmake", "cmake"], entries)},
            nixpkgs,
        )
        self.assertEqual((row["name"], row["searchTerm"]), ("cmake", "cmake"))

    def test_marked_broken_from_the_index(self):
        nixpkgs = {"a": pkg("a"), "b": pkg("b")}
        nixpkgs["a"]["meta"]["broken"] = True
        entries = [nix("a", "1", "newest"), nix("b", "1", "newest")]
        a, b = build_rows(
            {
                "a": project("a", ["a"], entries[:1]),
                "b": project("b", ["b"], entries[1:]),
            },
            nixpkgs,
        )
        self.assertTrue(a["markedBroken"])
        self.assertNotIn("markedBroken", b)

    def test_direct_maintainers_beside_teams(self):
        def person(handle):
            return {"github": handle, "githubId": 1}

        nixpkgs = {"gdal": pkg("gdal"), "plain": pkg("plain"), "old": pkg("old")}
        geo = {"shortName": "Geospatial"}
        nixpkgs["gdal"]["meta"].update(
            teams=[geo],
            maintainers=[person("tviti"), person("l0b0"), person("sikmir")],
            nonTeamMaintainers=[person("tviti")],
        )
        nixpkgs["plain"]["meta"].update(
            teams=[geo],
            maintainers=[person("l0b0")],
            nonTeamMaintainers=[person("l0b0")],  # the same: not repeated
        )
        nixpkgs["old"]["meta"].update(teams=[geo], maintainers=[person("x")])
        entries = [nix(n, "1", "newest") for n in ("gdal", "old", "plain")]
        gdal, old, plain = build_rows(
            {e["srcname"]: project(e["srcname"], [e["srcname"]], [e]) for e in entries},
            nixpkgs,
        )
        self.assertEqual(gdal["nonTeamMaintainers"], ["tviti"])
        self.assertNotIn("nonTeamMaintainers", plain)
        self.assertNotIn("nonTeamMaintainers", old)  # the index doesn't say

    def test_marked_insecure_from_the_index(self):
        nixpkgs = {"a": pkg("a"), "a-bin": pkg("a"), "b": pkg("b")}
        nixpkgs["a"]["meta"]["knownVulnerabilities"] = ["CVE-2020-25031"]
        nixpkgs["a-bin"]["meta"]["knownVulnerabilities"] = [
            "CVE-2020-25031",  # once
            "Uses Electron 37, EOL",
        ]
        entries = [nix("a", "1", "newest"), nix("b", "1", "newest")]
        a, b = build_rows(
            {
                "a": project("a", ["a", "a-bin"], entries[:1]),
                "b": project("b", ["b"], entries[1:]),
            },
            nixpkgs,
        )
        self.assertEqual(
            a["markedInsecure"], ["CVE-2020-25031", "Uses Electron 37, EOL"]
        )
        self.assertNotIn("markedInsecure", b)

    def test_teams_of_all_attributes_once(self):
        nixpkgs = {
            "steam": pkg("steam"),
            "steam-unwrapped": pkg("steam"),
            "orphan": pkg("orphan"),
        }
        nixpkgs["steam"]["meta"]["teams"] = [{"shortName": "Steam", "scope": "x"}]
        nixpkgs["steam-unwrapped"]["meta"]["teams"] = [
            {"shortName": "Steam"},
            {"shortName": "Gaming"},
            {"scope": "no short name"},
        ]
        entries = [nix("steam", "1", "newest"), nix("orphan", "1", "newest")]
        orphan, steam = build_rows(
            {
                "steam": project("steam", ["steam", "steam-unwrapped"], entries[:1]),
                "orphan": project("orphan", ["orphan"], entries[1:]),
            },
            nixpkgs,
        )
        self.assertEqual(steam["teams"], ["Steam", "Gaming"])
        self.assertNotIn("teams", orphan)  # none: left out

    def test_versioned_python_sets_search_by_alias(self):
        entries = [nix("python313Packages.requests", "2.34.2", "newest")]
        [row] = self.rows(
            project(
                "python313Packages.requests",
                ["python313Packages.requests"],
                entries,
                "python:requests",
            )
        )
        self.assertEqual(row["name"], "python313Packages.requests")
        self.assertEqual(row["searchTerm"], "python3Packages.requests")
        self.assertEqual(row["dataFile"], "python_requests.json")

    def test_stale_marker_carried_to_every_row_of_the_project(self):
        rows = self.rows(
            project(
                "wesnoth",
                ["wesnoth", "wesnoth-devel"],
                self.WESNOTH,
                "wesnoth",
                staleSince="2026-09-01",
            )
        )
        self.assertEqual([r["staleSince"] for r in rows], ["2026-09-01", "2026-09-01"])

    def test_rows_sorted_by_name_ignoring_case(self):
        rows = self.rows(
            project("bbedit", ["bbedit"], [], "bbedit"),
            project("_1password-gui", ["_1password-gui"], [], "1password"),
            project("Zed", [], []),
        )
        self.assertEqual([r["name"] for r in rows], ["_1password-gui", "bbedit", "Zed"])


class SearchTerm(unittest.TestCase):
    def test_search_term(self):
        self.assertEqual(
            search_term("python314Packages.numpy"), "python3Packages.numpy"
        )
        self.assertEqual(
            search_term("haskellPackages.pandoc"), "haskellPackages.pandoc"
        )
        self.assertEqual(search_term("heroic"), "heroic")


class SourceLinks(unittest.TestCase):
    NIXPKGS = {
        "wesnoth": {"meta": {"position": "pkgs/by-name/we/wesnoth/package.nix:147"}},
        "heroic": {"meta": {}},  # no position recorded
        "heroic-unwrapped": {
            "meta": {"position": "pkgs/by-name/he/heroic-unwrapped/package.nix:135"}
        },
    }

    def test_source_url(self):
        self.assertEqual(
            source_url("pkgs/by-name/we/wesnoth/package.nix:147", "abc123"),
            "https://github.com/NixOS/nixpkgs/blob/abc123/pkgs/by-name/we/wesnoth/package.nix#L147",
        )
        self.assertEqual(
            source_url("pkgs/top-level/all-packages.nix", "nixos-unstable"),
            "https://github.com/NixOS/nixpkgs/blob/nixos-unstable/pkgs/top-level/all-packages.nix",
        )

    def test_first_attr_with_a_position(self):
        rows = [
            {"attrs": ["wesnoth"]},
            {"attrs": ["heroic", "heroic-unwrapped"]},
            {"attrs": []},  # not in nixpkgs
            {"attrs": ["gone"]},  # not in the index
        ]
        add_source_links(rows, self.NIXPKGS, "rev")
        self.assertTrue(
            rows[0]["source"].endswith("/rev/pkgs/by-name/we/wesnoth/package.nix#L147")
        )
        self.assertTrue(
            rows[1]["source"].endswith(
                "/rev/pkgs/by-name/he/heroic-unwrapped/package.nix#L135"
            )
        )
        self.assertNotIn("source", rows[2])
        self.assertNotIn("source", rows[3])


class NewestVersion(unittest.TestCase):
    """refVersion: the newest version elsewhere."""

    def ref(self, entries):
        (row,) = build_rows(
            {"p": project("p", ["p"], [nix("p", "1.0", "outdated"), *entries], "p")}, {}
        )
        return row["refVersion"]

    def test_only_nix_packages_it(self):
        """msedgedriver: a stable branch got the update first (a backport);
        Repology marks it unique, not newest, as no other family has it."""
        entries = [
            other("nix_stable_26_05", "1.2", "unique"),
            other("nix_stable_25_11", "0.9", "outdated"),
        ]
        self.assertEqual(self.ref(entries), "1.2")

    def test_unique_only_when_none_is_newest(self):
        entries = [other("debian", "1.1", "newest"), other("odd", "9.9", "unique")]
        self.assertEqual(self.ref(entries), "1.1")

    def test_the_highest_not_the_first(self):
        entries = [other("a", "1.9", "newest"), other("b", "1.10", "newest")]
        self.assertEqual(self.ref(entries), "1.10")

    def test_none_known(self):
        self.assertIsNone(self.ref([other("a", "0.9", "outdated")]))


class ChannelVersions(unittest.TestCase):
    """nixVersion from the channel's index, when Repology hasn't caught up."""

    def row(self, status, channel, ref="2.0", attrs=("p",), index=None):
        entries = [nix("p", "1.0", status)]
        if ref:
            entries.append(other("debian", ref, "newest"))
        (row,) = build_rows({"p": project("p", list(attrs), entries, "p")}, {})
        index = index or {a: pkg(a, version=channel) for a in attrs}
        changed = channel_versions([row], index)
        return row, changed

    def test_caught_up(self):
        """microsoft-edge, 2026-10-08: the channel had .62, Repology .53."""
        row, changed = self.row("outdated", "2.0")
        self.assertEqual(changed, ["p"])
        self.assertEqual(
            (row["nixVersion"], row["nixStatus"], row["repologyVersion"]),
            ("2.0", "newest", "1.0"),
        )

    def test_still_behind(self):
        row, _ = self.row("outdated", "1.5")
        self.assertEqual((row["nixVersion"], row["nixStatus"]), ("1.5", "outdated"))

    def test_newest_stays_newest(self):
        row, _ = self.row("newest", "1.1", ref=None)
        self.assertEqual((row["nixVersion"], row["nixStatus"]), ("1.1", "newest"))

    def test_outdated_against_nothing_named(self):
        row, _ = self.row("outdated", "1.1", ref=None)
        self.assertEqual((row["nixVersion"], row["nixStatus"]), ("1.1", "outdated"))

    def test_not_older(self):
        row, changed = self.row("outdated", "0.9")
        self.assertEqual((changed, row["nixVersion"]), ([], "1.0"))
        self.assertNotIn("repologyVersion", row)

    def test_letters_only_are_repology_rules(self):
        """thunderbird-esr-bin: 153.3.1esr, which Repology has as 153.3.1."""
        row, changed = self.row("outdated", "1.0esr")
        self.assertEqual((changed, row["nixVersion"]), ([], "1.0"))

    def test_attributes_disagreeing(self):
        index = {"p": pkg("p", version="2.0"), "q": pkg("q", version="1.0")}
        _, changed = self.row("outdated", None, attrs=("p", "q"), index=index)
        self.assertEqual(changed, [])

    def test_a_kept_series_too(self):
        """firefox-esr, 2026-10-15: the channel had 153.5.0esr, Repology
        153.4.0. Its status stays: still kept beside the newer line."""
        row, changed = self.row("legacy", "1.1esr")
        self.assertEqual(changed, ["p"])
        self.assertNotIn("nixVulnerable", row)  # Repology's, for 1.0
        self.assertEqual(
            (row["nixVersion"], row["nixStatus"], row["repologyVersion"]),
            ("1.1esr", "legacy", "1.0"),
        )

    def test_kept_beside_the_channels_version(self):
        """firefox-esr, 2026-10-15: kept beside firefox, 158.0 in the channel,
        157.0.1 still on Repology."""
        entries = [
            nix("firefox-esr", "153.5.0esr", "legacy"),
            nix("firefox", "157.0.1", "legacy"),
            other("arch", "158.0", "newest"),
        ]
        rows = build_rows(
            {"f": project("firefox", ["firefox-esr", "firefox"], entries, "firefox")},
            {},
        )
        esr = next(r for r in rows if r["name"] == "firefox-esr")
        index = {"firefox": pkg("firefox", version="158.0")}
        channel_versions(rows, index)
        self.assertEqual(esr["keptBeside"], {"attr": "firefox", "version": "158.0"})
        # Not an older one (the channel behind Repology).
        channel_versions(rows, {"firefox": pkg("firefox", version="157.0")})
        self.assertEqual(esr["keptBeside"]["version"], "158.0")

    def test_statuses_left_alone(self):
        """Versions Repology distrusts or can't order."""
        for status in ("untrusted", "noscheme", "ignored"):
            with self.subTest(status):
                _, changed = self.row(status, "2.0")
                self.assertEqual(changed, [])


class Families(unittest.TestCase):
    def test_one_file_one_version_one_homepage(self):
        src = "https://github.com/NixOS/nixpkgs/blob/abc/pkgs/x/indi-3rdparty.nix#L{}"
        rows = [
            {
                "name": f"indi-3rdparty.indi-{n}",
                "source": src.format(i),
                "nixVersion": "2.2.4",
                "homepage": "https://indilib.org",
            }
            for i, n in enumerate(("a", "b", "c"))
        ] + [
            # The same file, another module's version and homepage (perl).
            {
                "name": "perlA",
                "source": src.format(9),
                "nixVersion": "0.09",
                "homepage": "https://metacpan.org/a",
            },
            {
                "name": "perlB",
                "source": src.format(10),
                "nixVersion": "0.09",
                "homepage": "https://metacpan.org/b",
            },
            # A set updated in bulk: never.
            {
                "name": "rPackages.a",
                "set": "rPackages",
                "source": src.format(1),
                "nixVersion": "2.2.4",
                "homepage": "https://indilib.org",
            },
        ]
        rows_module.add_families(rows)
        keys = [r.get("family") for r in rows]
        self.assertTrue(keys[0] and keys[0] == keys[1] == keys[2])
        self.assertEqual(keys[3:], [None, None, None])

    def test_label(self):
        self.assertEqual(
            rows_module.family_label(["indi-3rdparty.indi-a", "indi-3rdparty.indi-b"]),
            "indi-3rdparty.indi-*",
        )
        self.assertIsNone(rows_module.family_label(["aroccStdenv", "zigStdenv"]))
