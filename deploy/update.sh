#!/bin/bash
set -Eeuo pipefail

readonly COMPOSE_DIR=/opt/dnd-wiki
readonly BACKUP_SERVICE=dnd-wiki-backup.service
readonly LOCK_FILE=/run/lock/dnd-wiki-update.lock

previous_commit="not recorded"
skip_backup=false

usage() {
    echo "Usage: sudo $COMPOSE_DIR/deploy/update.sh [--skip-backup]"
    echo
    echo "  --skip-backup  Deploy without a pre-update backup (testing/emergencies only)."
}

case "${1:-}" in
    "") ;;
    --skip-backup)
        skip_backup=true
        ;;
    -h|--help)
        usage
        exit 0
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac
if (( $# > 1 )); then
    usage >&2
    exit 2
fi

show_failure_details() {
    exit_status=$?
    trap - ERR

    echo >&2
    echo "D&D Wiki update failed. The previous commit was: $previous_commit" >&2
    echo "The existing containers may still be serving the previous image." >&2

    if [[ -d "$COMPOSE_DIR" ]]; then
        cd "$COMPOSE_DIR"
        docker compose ps >&2 || true
        docker compose logs --tail=100 wiki caddy >&2 || true
    fi

    echo "Do not downgrade the database blindly. See DEPLOYMENT.md for rollback instructions." >&2
    exit "$exit_status"
}
trap show_failure_details ERR

if (( EUID != 0 )); then
    echo "Run this script as root, for example: sudo $COMPOSE_DIR/deploy/update.sh" >&2
    exit 1
fi

for command_name in docker flock git systemctl; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "Required command is not installed: $command_name" >&2
        exit 1
    fi
done

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "Another D&D Wiki update is already running." >&2
    exit 1
fi

cd "$COMPOSE_DIR"

for required_file in compose.yaml deploy/wiki.env deploy/caddy.env; do
    if [[ ! -r "$required_file" ]]; then
        echo "Required deployment file is missing or unreadable: $COMPOSE_DIR/$required_file" >&2
        exit 1
    fi
done

current_branch="$(git branch --show-current)"
if [[ -z "$current_branch" ]]; then
    echo "The repository is in detached-HEAD state. Check out its deployment branch first." >&2
    exit 1
fi

if ! upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null)"; then
    echo "Branch '$current_branch' has no configured upstream branch." >&2
    exit 1
fi
remote_name="${upstream%%/*}"
remote_branch="${upstream#*/}"

if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "Tracked files have local changes. Commit or remove them before updating:" >&2
    git status --short >&2
    exit 1
fi

previous_commit="$(git rev-parse HEAD)"
echo "Current revision: $previous_commit"

if [[ "$skip_backup" == true ]]; then
    echo "WARNING: Skipping the pre-update backup at the operator's request." >&2
else
    if ! systemctl cat "$BACKUP_SERVICE" >/dev/null 2>&1; then
        echo "The required backup service is not installed: $BACKUP_SERVICE" >&2
        echo "Complete the backup setup in DEPLOYMENT.md or explicitly use --skip-backup." >&2
        exit 1
    fi

    echo "Creating the pre-update backup..."
    systemctl start "$BACKUP_SERVICE"
    if [[ "$(systemctl show --property=Result --value "$BACKUP_SERVICE")" != "success" ]]; then
        echo "The pre-update backup did not complete successfully." >&2
        systemctl status "$BACKUP_SERVICE" --no-pager >&2 || true
        exit 1
    fi
fi

echo "Fetching $upstream..."
git fetch --prune "$remote_name"
git pull --ff-only "$remote_name" "$remote_branch"
new_commit="$(git rev-parse HEAD)"
echo "Deploying revision: $new_commit"

docker compose config --quiet

echo "Pulling Caddy and building the wiki image..."
docker compose pull caddy
docker compose build --pull wiki
docker compose run --rm --no-deps --entrypoint caddy caddy \
    validate --config /etc/caddy/Caddyfile

echo "Recreating services and waiting for health checks..."
docker compose up -d --force-recreate --remove-orphans --wait --wait-timeout 180

echo "Checking the database migration state..."
docker compose exec -T wiki flask db check

docker compose ps
echo "D&D Wiki update completed successfully: $previous_commit -> $new_commit"
