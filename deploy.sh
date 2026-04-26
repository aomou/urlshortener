#!/usr/bin/env bash
set -o errexit

# build 階段已經在 Dockerfile 跑 collectstatic，靜態檔住在 image 裡，由 WhiteNoise serve
docker compose build
docker compose run --rm web python manage.py migrate
docker compose up -d
