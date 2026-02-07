from django.contrib import admin
from .models_feature import EmpresaFeature

@admin.register(EmpresaFeature)
class EmpresaFeatureAdmin(admin.ModelAdmin):
    list_display = ("empresa", "exportar_funcionarios", "importar_funcionarios", "criar_funcionario", "editar_funcionario", "excluir_funcionario", "gerar_relatorio", "criar_lancamento", "editar_lancamento", "excluir_lancamento", "exportar_lancamentos", "gerar_sefip")
    list_filter = ("exportar_funcionarios", "importar_funcionarios", "criar_funcionario", "editar_funcionario", "excluir_funcionario", "gerar_relatorio", "criar_lancamento", "editar_lancamento", "excluir_lancamento", "exportar_lancamentos", "gerar_sefip")
    search_fields = ("empresa__nome",)
