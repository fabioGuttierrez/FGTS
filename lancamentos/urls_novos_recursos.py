"""
URLs para SEFIP, Importação Legada e Conferência de Lançamentos
"""

from django.urls import path
from . import views

urlpatterns = [
    # ===== EXPORTAÇÃO SEFIP =====
    path('sefip/exportar/', views.exportar_sefip, name='exportar_sefip'),
    path('sefip/preview/<int:empresa_id>/', views.preview_sefip, name='preview_sefip'),
    
    # ===== IMPORTAÇÃO DADOS LEGADOS =====
    path('importacao/upload/', views.upload_dados_legados, name='upload_dados_legados'),
    path('importacao/status/<int:import_id>/', views.status_importacao, name='status_importacao'),
    
    # ===== CONFERÊNCIA DE LANÇAMENTOS =====
    path('conferencia/listar/<int:empresa_id>/', views.listar_conferencias, name='conferencia_listar'),
    path('conferencia/<int:conferencia_id>/editar/', views.conferir_lancamento, name='conferencia_editar'),
    path('conferencia/<int:conferencia_id>/rejeitar/', views.rejeitar_lancamento, name='conferencia_rejeitar'),
    path('conferencia/relatorio/<int:empresa_id>/', views.relatorio_conferencias, name='conferencia_relatorio'),
]
