#!/bin/sh
set -eu

python manage.py migrate --noinput

exec gunicorn DjangoForAI.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers 2 \
  --timeout 120 \
  --graceful-timeout 30
