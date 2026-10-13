#!/bin/sh
set -eu

flask db upgrade
exec "$@"
