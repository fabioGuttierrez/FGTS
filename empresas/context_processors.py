from django.conf import settings

def is_admin_empresa(request):
    user = request.user
    empresa = getattr(user, "empresa", None)
    if user.is_authenticated and empresa:
        return {"is_admin_empresa": user.roles_empresas.filter(empresa=empresa, role="admin").exists()}
    return {"is_admin_empresa": False}
