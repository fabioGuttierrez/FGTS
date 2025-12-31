#!/bin/bash
# Script de inicialização para Coolify

# Coleta arquivos estáticos
python manage.py collectstatic --noinput

# Aplica migrations
python manage.py migrate --noinput

# Cria superuser se não existir
python manage.py shell << EOF
from usuarios.models import Usuario
if not Usuario.objects.filter(username='admin').exists():
    Usuario.objects.create_superuser('admin', 'admin@example.com', 'senha123')
    print('Superuser criado!')
EOF

# Inicia Gunicorn com 2 workers (otimizado para VPS com recursos limitados)
exec gunicorn --bind 0.0.0.0:8000 --workers 2 --timeout 120 fgtsweb.wsgi:application
