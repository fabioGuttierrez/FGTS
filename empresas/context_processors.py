from django.conf import settings


def is_admin_empresa(request):
    """
    Retorna flag de admin da empresa atual, mas de forma resiliente.

    Cenário de 500: usuário autenticado sem vínculo de empresa (ou FK inexistente)
    estourava DoesNotExist ao acessar user.empresa. Aqui tratamos de forma
    segura e retornamos False se não houver empresa vinculada ou se o registro
    não existir.
    """

    user = request.user
    if not user.is_authenticated:
        return {"is_admin_empresa": False}

    # Tentar obter empresa vinculada sem quebrar em caso de FK faltando
    try:
        empresa = getattr(user, "empresa", None)
        # Força acesso ao objeto relacionado apenas se existir referência
        if empresa is None:
            return {"is_admin_empresa": False}
        # Se o related_object não existe mais, captura DoesNotExist
        _ = empresa.id  # força avaliação
    except Exception:
        return {"is_admin_empresa": False}

    return {
        "is_admin_empresa": user.roles_empresas.filter(empresa=empresa, role="admin").exists()
    }
