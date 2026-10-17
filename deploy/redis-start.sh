#!/bin/sh
set -eu
umask 077
password="$(cat /run/secrets/redis_password)"
test -n "$password"
printf 'requirepass %s\nappendonly yes\nmaxmemory-policy noeviction\n' "$password" > /tmp/redis-production.conf
exec redis-server /tmp/redis-production.conf
