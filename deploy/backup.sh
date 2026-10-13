#!/bin/bash
set -Eeuo pipefail

readonly COMPOSE_DIR=/opt/dnd-wiki
readonly BACKUP_ENV=/etc/dnd-wiki/backup.env
readonly LOCK_FILE=/run/lock/dnd-wiki-backup.lock

if [[ ! -r "$BACKUP_ENV" ]]; then
    echo "Cannot read $BACKUP_ENV" >&2
    exit 1
fi

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "Another D&D Wiki backup is already running." >&2
    exit 1
fi

set -a
# shellcheck source=/dev/null
source "$BACKUP_ENV"
set +a

cd "$COMPOSE_DIR"

wiki_was_running=false
if docker compose ps --status running --services | grep -Fxq wiki; then
    wiki_was_running=true
fi

restart_wiki() {
    if [[ "$wiki_was_running" == true ]]; then
        docker compose up -d wiki
    fi
}
trap restart_wiki EXIT

if [[ "$wiki_was_running" == true ]]; then
    docker compose stop --timeout 30 wiki
fi

restic backup \
    /srv/dnd-wiki/app-data \
    /srv/dnd-wiki/caddy-data \
    /opt/dnd-wiki/deploy/wiki.env \
    /opt/dnd-wiki/deploy/caddy.env \
    --tag dnd-wiki

restart_wiki
wiki_was_running=false
trap - EXIT

restic forget \
    --tag dnd-wiki \
    --keep-daily 7 \
    --keep-weekly 4 \
    --keep-monthly 12 \
    --prune
