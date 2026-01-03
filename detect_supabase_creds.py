"""
Detectar credenciais Supabase PostgreSQL do novo projeto
"""
import re

# JWT token do Supabase
jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFieWlwZmN5cW5hcHRzdGlkcGhqIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2NzM5NjU2NSwiZXhwIjoyMDgyOTcyNTY1fQ.7f10RSykX1bJEIedkuAMTMPcRBzU3Zr6_cmsAbFA8xw"
api_url = "https://qbyipfcyqnaptstidphj.supabase.co"

# Extrair project ID do URL
project_id = re.search(r'https://(.+?)\.supabase\.co', api_url).group(1)

print("CREDENCIAIS SUPABASE DETECTADAS:")
print(f"Project ID: {project_id}")
print(f"Host: db.{project_id}.supabase.co")
print(f"Port: 5432")
print(f"Database: postgres")
print(f"User: postgres")
print(f"Password: (você precisa fornecer - gerada no painel)")
print()
print("Para encontrar a senha:")
print("1. Acesse: https://app.supabase.com/project/{}/settings/database".format(project_id))
print("2. Copie a 'Connection string' completa")
print("3. Ou use 'Reset password' para gerar uma nova")
