# shellcheck shell=bash
# Retakes the page's screenshots in assets/screenshots/ (the README's and the social
# preview), from the live data: nix run .#screenshots, from the repository.
#
# Takes, in each of the page's palettes: desktop-{dark,light}.png (1280px
# wide, at 2x, with a panel open), mobile-{dark,light}.png (390px, at 2x) and
# social-preview.png (a 1280x640 card at 2x, scripts/social-preview.html,
# around the dark desktop shot), then compresses them. Classic's have those
# names; Catppuccin's (Latte when light, Mocha when dark) end in -catppuccin:
# desktop-dark-catppuccin.png, ..., social-preview-catppuccin.png.
#
# Which page depends on the data: a list-based instance's shows its list (the
# shots above); every package's (a community instance: allPackages) its
# overview of all of nixpkgs, the page it opens on, in files starting with
# overview-: overview-desktop-dark.png (taller, 1280x1180, no panel), ...,
# overview-social-preview.png.
#
# Which data, with the page's current code (page/), so what's shown is what's
# live with this code:
#   - in nixkeeper's own repository (its origin is nixkeeper/nixkeeper), by
#     default both sets: the overview from the community instance
#     (nixkeeper.com) and the list from the demo (demo.nixkeeper.com, a fork
#     tracking its maintainer's packages and the gaming team's);
#   - in any other copy, by default its own data: its data branch on GitHub
#     (from its origin remote), the set that data makes;
#   - --data <url or folder>: that data alone, the set it makes;
#   - --overview-data and --list-data <url or folder, or none>: each set's
#     data (none: leave that set's files as they are).
#
#   nix run .#screenshots -- --browser <name or path> [--open <panel>]
#                            [--data <url> | --overview-data <url>
#                             --list-data <url>] [--port <port>]
#
# The browser has to be Chromium-based (the script uses Chromium's headless
# screenshot flags), and is always named:
#   - a nixpkgs package, fetched from this flake's nixpkgs when it's used:
#     google-chrome, chromium, ungoogled-chromium, brave, microsoft-edge,
#     vivaldi (not every one is available everywhere: chromium and
#     ungoogled-chromium are Linux-only);
#   - or a path to a browser's executable, e.g. on macOS
#     "/Applications/Chromium.app/Contents/MacOS/Chromium".
# Firefox can't be used: its headless screenshots are taken as soon as the
# page loads, before the page has fetched its data.
#
# --open picks the panel open in the list's desktop shots: <row>:<panel>, or
# none. The row is a package's name as the page shows it, or a position in
# the page's order (1 is the first row; past the last, the last). The panel
# is info (its details), build (its Hydra builds), update (its latest
# nixpkgs-update attempt), or auto: update if that has something to show
# (not just "none reported" or "not attempted"), else build likewise, else
# info. Default: 4:auto, a few rows of the table above the panel, the whole
# panel in the shot. The phone shots show the plain list; the
# social preview reuses the dark desktop shot.
#
# A data's address is the folder holding index.json: a URL, or a local
# folder (served next to the page).
#
# --port is the port of the local server that serves the page to the browser.
# Default: 8799.
#
# Each can also be set in the environment (OPEN, DATA, OVERVIEW_DATA,
# LIST_DATA, PORT); the argument wins.

set -euo pipefail

usage() {
	echo "Usage: nix run .#screenshots -- --browser <name or path>" >&2
	echo "  <name>: a Chromium-based browser in nixpkgs: google-chrome, chromium," >&2
	echo "          ungoogled-chromium, brave, microsoft-edge, vivaldi" >&2
	echo "  <path>: a Chromium-based browser's executable" >&2
	echo "Options:" >&2
	echo "  --open <row>:<info|build|update|auto>, or none: the panel open in the" >&2
	echo "          list's desktop shots; the row is a package's name or a" >&2
	echo "          position (default: 4:auto)" >&2
	echo "  --data <url or folder>: that data alone (the folder with index.json):" >&2
	echo "          a list-based instance's makes the list's shots, every" >&2
	echo "          package's the overview's" >&2
	echo "  --overview-data, --list-data <url or folder, or none>: each set's data" >&2
	echo "          (default, in nixkeeper's repository: nixkeeper.com's and" >&2
	echo "          demo.nixkeeper.com's; in a copy: its own data branch)" >&2
	echo "  --port <port>: the local server's port (default: 8799)" >&2
	echo "See scripts/screenshots.sh for more." >&2
	exit "${1:-1}"
}

# The community instance's data (its data branch: nixkeeper.com's
# Cloudflare turns scripts away), and the demo's page (its data is where the
# page says: a fork's data branch, wherever the fork lives).
COMMUNITY_DATA=https://raw.githubusercontent.com/nixkeeper/nixkeeper/data/data/
DEMO_PAGE=https://demo.nixkeeper.com/

browser=
while [ $# -gt 0 ]; do
	case $1 in
	--browser)
		[ $# -ge 2 ] || usage
		browser=$2
		shift 2
		;;
	--browser=*) browser=${1#--browser=} && shift ;;
	--open)
		[ $# -ge 2 ] || usage
		OPEN=$2
		shift 2
		;;
	--open=*) OPEN=${1#--open=} && shift ;;
	--data)
		[ $# -ge 2 ] || usage
		DATA=$2
		shift 2
		;;
	--data=*) DATA=${1#--data=} && shift ;;
	--overview-data)
		[ $# -ge 2 ] || usage
		OVERVIEW_DATA=$2
		shift 2
		;;
	--overview-data=*) OVERVIEW_DATA=${1#--overview-data=} && shift ;;
	--list-data)
		[ $# -ge 2 ] || usage
		LIST_DATA=$2
		shift 2
		;;
	--list-data=*) LIST_DATA=${1#--list-data=} && shift ;;
	--port)
		[ $# -ge 2 ] || usage
		PORT=$2
		shift 2
		;;
	--port=*) PORT=${1#--port=} && shift ;;
	-h | --help) usage 0 ;;
	*)
		echo "Unknown argument: $1" >&2
		usage
		;;
	esac
done
[ -n "$browser" ] || usage

[ -f flake.nix ] && [ -d page ] || {
	echo "Run this from the repository's root." >&2
	exit 1
}

open_given=${OPEN:+yes}
OPEN=${OPEN:-4:auto}
[[ $OPEN == none || $OPEN =~ ^[^:]+:(info|build|update|auto)$ ]] || {
	echo "--open: expected <row>:<info|build|update|auto>, or none (got: $OPEN)" >&2
	exit 1
}
PORT=${PORT:-8799}
[[ $PORT =~ ^[0-9]+$ ]] && [ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || {
	echo "--port: expected a port number (got: $PORT)" >&2
	exit 1
}

# The data of each run: "<data>" pairs, each making the set its data makes.
datas=()
if [ -n "${DATA:-}" ]; then
	[ -z "${OVERVIEW_DATA:-}${LIST_DATA:-}" ] || {
		echo "--data takes one data alone: not with --overview-data or --list-data" >&2
		exit 1
	}
	datas=("$DATA")
else
	# owner/repo from the origin remote: git@github.com:o/r.git or https://github.com/o/r
	repo=$(git remote get-url origin | sed -E 's#^.*github\.com[:/]##; s#\.git$##')
	if [ "$repo" = nixkeeper/nixkeeper ] || [ -n "${OVERVIEW_DATA:-}${LIST_DATA:-}" ]; then
		if [ -z "${LIST_DATA:-}" ]; then
			# The demo's data: where its page says it is.
			LIST_DATA=$(python3 - "$DEMO_PAGE" <<'EOF'
import re, sys, urllib.request
page = urllib.request.urlopen(sys.argv[1], timeout=30).read().decode()
m = re.search(r'<meta name="nixkeeper-data" content="([^"]+)"', page)
sys.exit(f"--list-data: {sys.argv[1]} doesn't say where its data is") if not m else print(m.group(1))
EOF
)
		fi
		OVERVIEW_DATA=${OVERVIEW_DATA:-$COMMUNITY_DATA}
		[ "$OVERVIEW_DATA" = none ] || datas+=("$OVERVIEW_DATA")
		[ "$LIST_DATA" = none ] || datas+=("$LIST_DATA")
	else
		datas=("https://raw.githubusercontent.com/$repo/data/data/")
	fi
fi
[ ${#datas[@]} -gt 0 ] || {
	echo "Nothing to take: both sets are none." >&2
	exit 1
}

case $browser in
*firefox*)
	echo "Firefox can't be used: it takes its headless screenshot before the page has" >&2
	echo "loaded its data. Use a Chromium-based browser." >&2
	exit 1
	;;
*/*) # a path
	[ -x "$browser" ] || {
		echo "Not an executable: $browser" >&2
		exit 1
	}
	chrome=$browser
	;;
*) # a nixpkgs package, from this flake's nixpkgs ($NIXPKGS, set by the app)
	[[ $browser =~ ^[A-Za-z0-9_-]+$ ]] || {
		echo "Not a package name: $browser" >&2
		exit 1
	}
	# Unfree ones (google-chrome, microsoft-edge, vivaldi) are allowed: it's
	# the one package asked for.
	pkg="(import ${NIXPKGS:?} { config.allowUnfree = true; }).\"$browser\""
	available=$(nix eval --impure --json --expr "$pkg.meta.available or false")
	if [ "$available" != true ]; then
		echo "nixpkgs has no $browser for this system: pass a path to a browser instead." >&2
		exit 1
	fi
	echo "Getting $browser from nixpkgs..."
	nix build --impure --no-link --expr "$pkg"
	chrome=$(nix eval --impure --raw --expr "(import $NIXPKGS { }).lib.getExe $pkg")
	;;
esac

work=$(mktemp -d)
site=$work/site
profile=$work/profile # a throwaway profile: nothing of yours is touched
mkdir -p "$site" "$work/out" "$profile"
server=
cleanup() {
	[ -n "$server" ] && kill "$server" 2>/dev/null
	pkill -f "user-data-dir=$profile" 2>/dev/null || true
	rm -rf "$work"
}
trap cleanup EXIT

python3 -m http.server "$PORT" --bind 127.0.0.1 --directory "$site" >/dev/null 2>&1 &
server=$!
sleep 1

# shot <name> <width> <height> <scale> <dark|light> <path>
shot() {
	local out=$work/out/$1.png scheme=1
	[ "$5" = dark ] && scheme=0
	"$chrome" --headless=new --disable-gpu --hide-scrollbars --no-first-run \
		--user-data-dir="$profile" --window-size="$2,$3" \
		--force-device-scale-factor="$4" --blink-settings=preferredColorScheme=$scheme \
		--virtual-time-budget=8000 --screenshot="$out" \
		"http://127.0.0.1:$PORT/$6" >/dev/null 2>&1 &
	# Chrome writes the screenshot but doesn't always exit: wait for the file.
	for _ in $(seq 60); do
		[ -s "$out" ] && break
		sleep 1
	done
	sleep 1
	pkill -f "user-data-dir=$profile" 2>/dev/null || true
	sleep 1
	[ -s "$out" ] || {
		echo "No screenshot for $1 (is the data reachable?)" >&2
		exit 1
	}
	echo "  $1"
}

# take <data>: the set that data makes, into $work/out.
take() {
	local data=$1 local_data='' mode page_data
	# A local folder: served next to the page, as data/ (below).
	if [[ $data != *://* ]]; then
		[ -f "$data/index.json" ] || {
			echo "No index.json in $data" >&2
			exit 1
		}
		local_data=$(cd "$data" && pwd)
	fi
	data=${data%/}/ # the folder, as the page expects it

	# The data has to be there, and so does the panel asked for: the
	# package on the page, and for build or update a cell that opens one
	# (packages not in nixpkgs have neither). Prints which page the data
	# shows: list or overview. --open only fails the overview when it's
	# the one data asked for.
	mode=$(python3 - "$data" "$OPEN" "$open_given" "${#datas[@]}" <<'EOF'
import json, os, sys, urllib.request
data, want, given, count = sys.argv[1:]
def read(name):
    try:
        if "://" not in data:
            with open(os.path.join(data, name)) as f:
                return json.load(f)
        with urllib.request.urlopen(data + name, timeout=30) as resp:
            return json.load(resp)
    except (OSError, ValueError) as e:
        sys.exit(f"couldn't read {data}{name} ({e})")
index = read("index.json")
if index.get("format", 1) < 2:
    sys.exit(f"{data}index.json is from nixkeeper 0.11.0 or older")
if index.get("allPackages"):
    # Every package (a community instance): its overview of all of nixpkgs,
    # with no rows to open a panel in.
    if given and want != "none" and count == "1":
        sys.exit("--open: every package's data shows its overview, with no panel to open")
    print("overview")
    sys.exit()
rows = {row["name"]: row for row in read("summary.json").get("packages", [])}
if not rows:
    sys.exit(f"{data}summary.json has no packages")
if want != "none":
    name, panel = want.rsplit(":", 1)
    if name.isdigit():
        # A position: the page knows its order, and takes the last row past it.
        if int(name) < 1:
            sys.exit("--open: positions start at 1")
    elif name not in rows:
        sys.exit(f"--open: no package {name!r} on the page")
    else:
        field = {"build": "builds", "update": "update"}.get(panel)
        if field and field not in rows[name]:
            sys.exit(f"--open: {name} has no {panel} panel (it's not in nixpkgs)")
print("list")
EOF
)

	# The page as it is in page/, pointed at the data, in the palette asked
	# for (?palette=<name>, saved as a visitor's choice before the page
	# draws), and able to open a panel once its rows are there
	# (?open=<row>:<panel>, as --open).
	rm -rf "${site:?}"/*
	cp page/* "$site/"
	page_data=$data
	if [ -n "$local_data" ]; then
		ln -s "$local_data" "$site/data"
		page_data=data/
	fi
	python3 - "$site/index.html" "$page_data" <<'EOF'
import sys
path, data = sys.argv[1:]
page = open(path).read()
# No scrollbar: --hide-scrollbars hides the window's, not the page's in the
# phone shots' frame, which showed as a white strip down their right edge.
page = page.replace(
    "<head>",
    f'''<head><meta name="nixkeeper-data" content="{data}">
<style>html{{scrollbar-width:none}}::-webkit-scrollbar{{display:none}}</style>
<script>localStorage.setItem('nixkeeper-palette',
  new URLSearchParams(location.search).get('palette') || 'classic');</script>''',
    1,
)
page = page.replace(
    "</body>",
    """<script>
const want = new URLSearchParams(location.search).get('open');
if (want) {
  const at = want.lastIndexOf(':');
  const [name, panel] = [want.slice(0, at), want.slice(at + 1)];
  // A cell's panel, when it has something to show: its button isn't one of
  // the "nothing to report" ones (none reported, not attempted, ...).
  const worth = (row, kind) => {
    const b = row.querySelector(`.failure-btn[data-kind="${kind}"]`);
    return b && !b.hasAttribute('data-quiet') ? b : null;
  };
  const t = setInterval(() => {
    const rows = [...document.querySelectorAll('tr.row')];
    if (!rows.length) return;
    const row = /^[0-9]+$/.test(name)
      ? rows[Math.min(+name, rows.length) - 1]
      : rows.find((r) => r.querySelector('.n')?.textContent === name);
    if (!row) return;
    clearInterval(t);
    const button =
      panel === 'auto'
        ? worth(row, 'update') || worth(row, 'build')
        : panel === 'info'
          ? null
          : row.querySelector(`.failure-btn[data-kind="${panel}"]`);
    if (button) button.click();
    else if (panel === 'info' || panel === 'auto') row.click();
  }, 100);
}
</script></body>""",
    1,
)
open(path, "w").write(page)
EOF
	# Chrome won't make a window narrower than about 500px, so the phone
	# shots are of the page in a 390px frame, centred in a wider window,
	# then cropped. The frame passes its own ?palette= on.
	cat >"$site/phone.html" <<'EOF'
<!doctype html><meta charset="utf-8">
<style>html,body{margin:0}iframe{border:0;width:390px;height:844px;display:block;margin:0 auto}</style>
<iframe></iframe>
<script>document.querySelector('iframe').src = 'index.html' + location.search;</script>
EOF
	cp scripts/social-preview.html "$site/"

	# The list's shots, or the overview's (overview-...): taller, to show its
	# cards, the search and what's newest, and no panel.
	local prefix='' height=860 card=social-preview.html palette suffix theme query
	if [ "$mode" = overview ]; then
		prefix=overview-
		height=1180
		card='social-preview.html?mode=overview'
	fi
	echo "Taking screenshots of the $mode (data: $data)..."
	for palette in classic catppuccin; do
		suffix=
		[ "$palette" = classic ] || suffix=-$palette
		for theme in dark light; do
			query="?palette=$palette"
			[ "$mode" = list ] && [ "$OPEN" != none ] && query="$query&open=$OPEN"
			shot "${prefix}desktop-$theme$suffix" 1280 "$height" 2 "$theme" "$query"
			shot "${prefix}mobile-$theme$suffix" 800 844 2 "$theme" "phone.html?palette=$palette"
			magick "$work/out/${prefix}mobile-$theme$suffix.png" -gravity center -crop 780x1688+0+0 +repage \
				"$work/out/${prefix}mobile-$theme$suffix.png"
		done
		# The social preview: a card (scripts/social-preview.html) with the
		# lockup, what nixkeeper watches, and the dark desktop shot, at 2x.
		cp "$work/out/${prefix}desktop-dark$suffix.png" "$site/shot.png"
		shot "${prefix}social-preview$suffix" 1280 640 2 dark "$card"
	done
}

for data in "${datas[@]}"; do
	take "$data"
done

echo "Compressing into assets/screenshots/..."
mkdir -p assets/screenshots
for f in "$work"/out/*.png; do
	pngquant --quality=80-95 --strip --speed 1 --force --output "assets/screenshots/$(basename "$f")" "$f"
done
du -ch assets/screenshots/*.png | tail -1
echo "Done. The social preview is uploaded by hand: Settings → General → Social preview"
echo "(overview-social-preview.png or social-preview.png, or their -catppuccin ones)."
