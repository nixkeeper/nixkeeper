# The NixOS module in a VM (checks.module on Linux; needs KVM, which CI has):
# the timers, the catch-up at boot, the frequent checks against data like a
# sync leaves, and the page with its data on nginx. The VM has no internet, so
# no real sync: the data is put there at boot, as if one had just run.
{ pkgs, self }:
pkgs.testers.runNixOSTest {
  name = "nixkeeper";

  nodes.machine = {
    imports = [ self.nixosModules.default ];
    services.nixkeeper = {
      enable = true;
      lists.maintainers = [ "iedame" ];
      nginx.virtualHost = "localhost";
    };

    # A sync from a minute ago, before the catch-up looks: one package, up
    # to date, nothing to look up.
    systemd.services.fake-recent-sync = {
      wantedBy = [ "multi-user.target" ];
      before = [ "nixkeeper-catch-up.service" ];
      requiredBy = [ "nixkeeper-catch-up.service" ];
      serviceConfig.Type = "oneshot";
      script = ''
        install -d -o nixkeeper -g nixkeeper /var/lib/nixkeeper /var/lib/nixkeeper/data
        cat > /var/lib/nixkeeper/data/index.json <<EOF
        {"checkedAt": "$(date -u -d '1 minute ago' +%Y-%m-%dT%H:%M:%S+00:00)",
         "verdicts": 1,
         "packages": [{"name": "unciv", "attrs": ["unciv"], "nixStatus": "newest"}]}
        EOF
        chown nixkeeper:nixkeeper /var/lib/nixkeeper/data/index.json
      '';
    };
  };

  testScript = ''
    import json

    machine.wait_for_unit("multi-user.target")
    machine.succeed("systemctl list-timers | grep nixkeeper-sync.timer")
    machine.succeed("systemctl list-timers | grep nixkeeper-checks.timer")

    with subtest("the catch-up at boot skips a recent sync"):
        machine.wait_until_fails("systemctl is-active --quiet nixkeeper-catch-up.service")
        # Not "log": the test driver's own logger is called that.
        journal = machine.succeed("journalctl -u nixkeeper-catch-up.service")
        assert "nothing to do" in journal, journal
        machine.fail("systemctl is-failed --quiet nixkeeper-catch-up.service")

    with subtest("the lists are the module's, as JSON"):
        lists = machine.succeed(
            "systemctl show nixkeeper-sync.service -p Environment"
            " | grep -o 'NIXKEEPER_LISTS=[^ ]*' | cut -d= -f2"
        ).strip()
        assert json.loads(machine.succeed(f"cat {lists}"))["maintainers"] == ["iedame"]

    with subtest("the checks wait for a first sync"):
        machine.succeed("mv /var/lib/nixkeeper/data/index.json /root/index.json")
        machine.succeed("systemctl start nixkeeper-checks.service")
        machine.succeed(
            "journalctl -u nixkeeper-checks.service | grep -q 'unmet condition'"
        )
        machine.succeed("mv /root/index.json /var/lib/nixkeeper/data/index.json")

    with subtest("the checks wait for a sync by this version"):
        # Data from an older nixkeeper (no "verdicts"): nothing published.
        machine.succeed(
            "cp /var/lib/nixkeeper/data/index.json /root/index.json"
            " && sed -i 's/\"verdicts\": 1,//' /var/lib/nixkeeper/data/index.json"
        )
        machine.succeed("systemctl start nixkeeper-checks.service")
        journal = machine.succeed("journalctl -u nixkeeper-checks.service")
        assert "until a full sync" in journal, journal
        machine.succeed("cp /root/index.json /var/lib/nixkeeper/data/index.json")

    with subtest("the frequent checks run against the data"):
        machine.succeed("systemctl start nixkeeper-checks.service")
        journal = machine.succeed("journalctl -u nixkeeper-checks.service")
        assert "No frequent update checks" in journal, journal
        assert "Nothing outdated" in journal, journal

    with subtest("nginx serves the page and the data next to it"):
        machine.wait_for_unit("nginx.service")
        machine.wait_for_open_port(80)
        assert "<title>nixkeeper" in machine.succeed("curl -sf http://localhost/")
        data = json.loads(machine.succeed("curl -sf http://localhost/data/index.json"))
        assert data["packages"][0]["name"] == "unciv"
        machine.fail("curl -sf --path-as-is http://localhost/data/../../etc/passwd")
  '';
}
