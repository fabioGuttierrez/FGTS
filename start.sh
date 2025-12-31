#!/bin/bash
# Script de inicialização para Coolify

# Aplica migrations
python manage.py migrate --noinput

# Cria superuser se não existir
python manage.py shell << EOF
from usuarios.models import Usuario
if not Usuario.objects.filter(username='admin').exists():
    Usuario.objects.create_superuser('admin', 'admin@example.com', 'senha123')
    print('Superuser criado!')
EOF

# Inicia Gunicorn
exec gunicorn --bind 0.0.0.0:8000 --workers 4 --timeout 120 fgtsweb.wsgi:application
