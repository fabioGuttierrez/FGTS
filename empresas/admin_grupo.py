from django.contrib import admin
from .models_grupo import GrupoEmpresa, FuncionarioVinculo, TransferenciaFuncionario

@admin.register(GrupoEmpresa)
class GrupoEmpresaAdmin(admin.ModelAdmin):
    list_display = ("nome", "cnpj_base", "empresa_principal", "data_criacao")
    search_fields = ("nome", "cnpj_base")
    autocomplete_fields = ("empresa_principal",)

@admin.register(FuncionarioVinculo)
class FuncionarioVinculoAdmin(admin.ModelAdmin):
    list_display = ("funcionario", "empresa", "data_admissao", "data_demissao", "motivo_saida")
    search_fields = ("funcionario__nome", "empresa__nome")
    list_filter = ("empresa", "motivo_saida")

@admin.register(TransferenciaFuncionario)
class TransferenciaFuncionarioAdmin(admin.ModelAdmin):
    list_display = ("funcionario", "empresa_origem", "empresa_destino", "data_transferencia", "usuario_responsavel")
    search_fields = ("funcionario__nome", "empresa_origem__nome", "empresa_destino__nome")
    list_filter = ("empresa_origem", "empresa_destino")
