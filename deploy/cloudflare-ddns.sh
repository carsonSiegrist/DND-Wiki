#!/bin/bash
set -Eeuo pipefail

readonly API_ROOT="https://api.cloudflare.com/client/v4"
readonly IP_TRACE_URL="https://cloudflare.com/cdn-cgi/trace"
readonly LOCK_FILE="/run/lock/dnd-wiki-cloudflare-ddns.lock"

required_variables=(
    CLOUDFLARE_API_TOKEN
    CLOUDFLARE_ZONE_ID
    CLOUDFLARE_RECORD_NAME
    CLOUDFLARE_PROXIED
)
for variable_name in "${required_variables[@]}"; do
    if [[ -z "${!variable_name:-}" ]]; then
        echo "Missing required setting: $variable_name" >&2
        exit 1
    fi
done

case "$CLOUDFLARE_PROXIED" in
    true|false) ;;
    *)
        echo "CLOUDFLARE_PROXIED must be true or false." >&2
        exit 1
        ;;
esac

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "A Cloudflare DDNS update is already running." >&2
    exit 1
fi

public_ip="$({
    curl --ipv4 --fail --silent --show-error "$IP_TRACE_URL"
} | awk -F= '$1 == "ip" { print $2; exit }')"

if [[ ! "$public_ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
    echo "Could not determine a valid public IPv4 address." >&2
    exit 1
fi

IFS=. read -r octet_1 octet_2 octet_3 octet_4 <<<"$public_ip"
for octet in "$octet_1" "$octet_2" "$octet_3" "$octet_4"; do
    if (( 10#$octet > 255 )); then
        echo "Public IPv4 lookup returned an invalid address." >&2
        exit 1
    fi
done

record_response="$(curl \
    --fail-with-body \
    --silent \
    --show-error \
    --get \
    --header "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
    --header "Content-Type: application/json" \
    --data-urlencode "type=A" \
    --data-urlencode "name=$CLOUDFLARE_RECORD_NAME" \
    --data-urlencode "per_page=2" \
    "$API_ROOT/zones/$CLOUDFLARE_ZONE_ID/dns_records")"

if [[ "$(jq -r '.success' <<<"$record_response")" != "true" ]]; then
    echo "Cloudflare rejected the DNS-record lookup:" >&2
    jq -c '.errors' <<<"$record_response" >&2
    exit 1
fi

record_count="$(jq '.result | length' <<<"$record_response")"
if [[ "$record_count" != "1" ]]; then
    echo "Expected exactly one A record named $CLOUDFLARE_RECORD_NAME; found $record_count." >&2
    exit 1
fi

record_id="$(jq -r '.result[0].id' <<<"$record_response")"
current_ip="$(jq -r '.result[0].content' <<<"$record_response")"
current_proxied="$(jq -r '.result[0].proxied' <<<"$record_response")"

if [[ "$current_ip" == "$public_ip" && "$current_proxied" == "$CLOUDFLARE_PROXIED" ]]; then
    exit 0
fi

payload="$(jq -n \
    --arg name "$CLOUDFLARE_RECORD_NAME" \
    --arg content "$public_ip" \
    --argjson proxied "$CLOUDFLARE_PROXIED" \
    '{type: "A", name: $name, content: $content, ttl: 1, proxied: $proxied}')"

update_response="$(curl \
    --fail-with-body \
    --silent \
    --show-error \
    --request PATCH \
    --header "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
    --header "Content-Type: application/json" \
    --data "$payload" \
    "$API_ROOT/zones/$CLOUDFLARE_ZONE_ID/dns_records/$record_id")"

if [[ "$(jq -r '.success' <<<"$update_response")" != "true" ]]; then
    echo "Cloudflare rejected the DNS-record update:" >&2
    jq -c '.errors' <<<"$update_response" >&2
    exit 1
fi

echo "Updated $CLOUDFLARE_RECORD_NAME to $public_ip."
