#!/usr/bin/env bash
set -o errexit

docker compose build
docker compose run --rm web python manage.py migrate
# 把 staticfiles 寫進 named volume，讓 nginx 能直接 serve
docker compose run --rm web python manage.py collectstatic --noinput
docker compose up -d
