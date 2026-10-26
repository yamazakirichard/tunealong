#!/usr/bin/env bash
# Gate 7: the compose deployment, end to end.
#
#   scripts/compose_test.sh        (or: make compose-test)
#
# Works from a clean copy of this checkout (tracked + new files, nothing
# ignored) in .compose-test/, so a local .env or data/ is never used or touched.
# Needs host port 8080 free. Steps:
#   1. defaults only (cp .env.example .env): healthy, UI at localhost:8080, no
#      auth, rubberband + ffmpeg in the image, files owned by PUID:PGID (1000)
#   2. fake MeTube override: Playwright smoke subset against the containers
#   3. PUID/PGID 1234 + SONGBOOK_BASE_PATH=/songbook + fake MeTube: the smoke
#      subset under the subpath, and every file written is owned by 1234:1234
#   4. auth on (bcrypt hash written with $$ in .env): 401 / 200, health open
#   5. static: no hardcoded hostnames, nothing outside Songbook/
#
# GATE_STEPS="1 3" runs only those steps; GATE_KEEP=1 leaves the last stack up.
set -uo pipefail
STEPS="${GATE_STEPS:-1 2 3 4 5}"
want() { case " $STEPS " in *" $1 "*) return 0;; *) return 1;; esac; }

SB="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$SB/.compose-test"
CO="$WORK/checkout"
FAILED=0
pass() { printf '  PASS  %s\n' "$*"; }
fail() { printf '  FAIL  %s\n' "$*"; FAILED=1; }
check() { local what=$1; shift; if "$@" >/tmp/songbook-gate-check.log 2>&1; then pass "$what"; else fail "$what"; sed 's/^/        /' /tmp/songbook-gate-check.log | tail -15; fi; }

as_root() { docker run --rm --user 0 --entrypoint sh -v "$WORK:/w" songbook:latest -c "$1"; }
probe() { docker run --rm --network host --entrypoint python -v "$SB/scripts:/s:ro" songbook:latest /s/http_probe.py "$@"; }
# Shell variables beat .env in Compose, and a PUID/PGID exported by the calling
# environment (common in linuxserver-style containers) would silently win. So
# every key .env.example defines is unset for compose; .env is the only source.
ENV_KEYS=$(grep -oE '^[A-Z_]+=' "$SB/.env.example" | tr -d = | sed 's/^/-u /' | tr '\n' ' ')
dc() { (cd "$CO" && env $ENV_KEYS docker compose "$@"); }

wait_healthy() {  # wait_healthy service...
    local svc deadline=$((SECONDS + 180))
    for svc in "$@"; do
        while :; do
            local cid state
            cid=$(dc ps -q "$svc")
            state=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || echo missing)
            [ "$state" = healthy ] && break
            if [ $SECONDS -ge $deadline ]; then echo "$svc: $state"; dc logs --tail 30 "$svc"; return 1; fi
            sleep 2
        done
    done
}

owned_by() {  # owned_by uid:gid dir — every file and dir under it
    local bad
    bad=$(as_root "find /w/checkout/data ! -user ${1%:*} -o ! -group ${1#*:}" | grep -v '^$' || true)
    [ -z "$bad" ] || { echo "not owned by $1:"; echo "$bad" | head -20; return 1; }
}

smoke() {  # smoke base-url
    docker run --rm --network host --ipc=host -e E2E_BASE_URL="$1" songbook:e2e npx playwright test 2>&1 | grep -E "✓|✘|passed|failed|Error" ; return "${PIPESTATUS[0]}"
}

down() { [ "${GATE_KEEP:-0}" = 1 ] && { echo "  (GATE_KEEP=1: leaving the stack up)"; return; }; dc -f compose.yml -f compose.fake-metube.yml down -v --remove-orphans >/dev/null 2>&1; as_root "rm -rf /w/checkout/data" >/dev/null 2>&1; }

not_published() {  # not_published service — no host port bindings at all
    local b; b=$(docker inspect -f '{{json .HostConfig.PortBindings}}' "$(dc ps -q "$1")")
    [ "$b" = "{}" ] || [ "$b" = "null" ] || { echo "$1 publishes: $b"; return 1; }
}

set_env() {  # set_env KEY=VALUE... — appended to a fresh copy of .env.example
    cp "$CO/.env.example" "$CO/.env"
    local kv; for kv in "$@"; do printf '%s\n' "$kv" >> "$CO/.env"; done
}

echo "== preparing a clean checkout in .compose-test/"
if docker compose ls -q | grep -qx songbook; then echo "a compose project named 'songbook' is already running; stop it first"; exit 2; fi
rm -rf "$CO" 2>/dev/null || as_root "rm -rf /w/checkout"
mkdir -p "$CO"
(cd "$SB" && git ls-files -z --cached --others --exclude-standard . | tar --null -T - -cf -) | tar -xf - -C "$CO"
[ -e "$CO/.env" ] && { echo "unexpected .env in the checkout"; exit 2; }

echo "== building images (app, test, e2e)"
dc -f compose.yml -f compose.fake-metube.yml build -q || exit 1
docker build -q --target e2e -t songbook:e2e "$CO" >/dev/null || exit 1

if want 1; then
echo "== 1. defaults: cp .env.example .env && docker compose up -d"
cp "$CO/.env.example" "$CO/.env"
dc up -d >/dev/null 2>&1
check "api, worker and metube reach healthy" wait_healthy api worker metube
check "UI loads at http://localhost:8080" probe http://localhost:8080/ --contains "<title>Songbook</title>"
check "API answers without auth" probe http://localhost:8080/api/library --contains '"Unsorted"'
check "rubberband --version in the image" dc exec -T api rubberband --version
check "ffmpeg -version in the image" dc exec -T api ffmpeg -version
check "data files owned by PUID:PGID 1000:1000" owned_by 1000:1000
check "MeTube is not published on the host" not_published metube
down
fi

if want 2; then
echo "== 2. fake MeTube override: Playwright smoke subset"
set_env
dc -f compose.yml -f compose.fake-metube.yml up -d >/dev/null 2>&1
check "stack with the fake MeTube is healthy" wait_healthy api worker metube
check "smoke subset passes at http://localhost:8080/" smoke http://localhost:8080/
down
fi

if want 3; then
echo "== 3. PUID/PGID 1234 + SONGBOOK_BASE_PATH=/songbook (fake MeTube)"
set_env PUID=1234 PGID=1234 SONGBOOK_BASE_PATH=/songbook
dc -f compose.yml -f compose.fake-metube.yml up -d >/dev/null 2>&1
check "stack is healthy under the subpath" wait_healthy api worker metube
check "UI loads at /songbook/" probe http://localhost:8080/songbook/ --contains "<title>Songbook</title>"
check "/songbook redirects to /songbook/" probe http://localhost:8080/songbook --expect 308
check "API at /songbook/api/health" probe http://localhost:8080/songbook/api/health --contains ok
check "nothing served at the root" probe http://localhost:8080/api/health --expect 404
check "smoke subset (UI, API, media) passes under /songbook/" smoke http://localhost:8080/songbook/
check "every file written is owned by 1234:1234" owned_by 1234:1234
down
fi

if want 4; then
echo "== 4. built-in auth (hash written with \$\$ in .env)"
HASH=$(docker run --rm --entrypoint python songbook:latest -c "import bcrypt; print(bcrypt.hashpw(b'gate pass', bcrypt.gensalt(rounds=10)).decode())")
set_env SONGBOOK_AUTH_USER=gate "SONGBOOK_AUTH_PASSWORD_HASH=${HASH//\$/\$\$}"
grep -q 'SONGBOOK_AUTH_PASSWORD_HASH=\$\$2b\$\$' "$CO/.env" && pass ".env holds the hash with \$\$" || fail ".env hash escaping"
dc up -d api >/dev/null 2>&1
check "api is healthy with auth on" wait_healthy api
check "/api/health stays open" probe http://localhost:8080/api/health
check "unauthenticated API request gets 401" probe http://localhost:8080/api/library --expect 401
check "unauthenticated UI request gets 401" probe http://localhost:8080/ --expect 401
check "wrong password gets 401" probe http://localhost:8080/api/library --user gate --password nope --expect 401
check "right password gets 200 (API)" probe http://localhost:8080/api/library --user gate --password "gate pass"
check "right password gets 200 (UI)" probe http://localhost:8080/ --user gate --password "gate pass" --contains "<title>Songbook</title>"
down
fi

if want 5; then
echo "== 5. static checks"
check "no hardcoded hostnames; nothing references a path outside Songbook/" python3 "$SB/scripts/check_self_contained.py"
fi

[ "${GATE_KEEP:-0}" = 1 ] || as_root "rm -rf /w/checkout" >/dev/null 2>&1
echo
if [ $FAILED = 0 ]; then echo "Gate 7: all checks passed"; else echo "Gate 7: FAILED"; fi
exit $FAILED
