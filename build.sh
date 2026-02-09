#!/usr/bin/env bash
set -o errexit

# 安裝 uv
pip install --upgrade uv

# 安裝依賴（使用 lock）
uv sync --frozen

# Django migrations
python manage.py migrate

# Static files
python manage.py collectstatic --noinput

# Create superuser if it doesn't exist
python manage.py shell -c "
from django.contrib.auth import get_user_model;
User = get_user_model();
if not User.objects.filter(username='admin').exists():
    import os;
    password = os.getenv('DJANGO_SUPERUSER_PASSWORD');
    if password:
        User.objects.create_superuser('admin', 'admin@example.com', password);
        print('Superuser created successfully');
    else:
        print('DJANGO_SUPERUSER_PASSWORD not set, skipping superuser creation');
"