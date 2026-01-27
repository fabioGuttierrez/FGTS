"""
URLs para SEFIP, Importação Legada e Conferência de Lançamentos
"""

from django.urls import path
from . import views

urlpatterns = [
    # ===== LEGACY IMPORT (NOVA INTERFACE) =====
    path('legacy-import/', views.LegacyImportView.as_view(), name='legacy-import'),
    path('legacy-import/resultado/', views.LegacyImportResultView.as_view(), name='legacy-import-result'),
    
    # ===== CONFERÊNCIA DE LANÇAMENTOS =====
    path('conferencia/<int:empresa_id>/', views.ConferenciaListView.as_view(), name='conferencia-list'),
    path('conferencia/<int:conferencia_id>/detalhe/', views.ConferenciaDetailView.as_view(), name='conferencia-detail'),
    path('conferencia/<int:conferencia_id>/conferir/', views.ConferenciaConferirView.as_view(), name='conferencia-conferir'),
    path('conferencia/<int:conferencia_id>/rejeitar/', views.ConferenciaRejeitarView.as_view(), name='conferencia-rejeitar'),
    path('conferencia/<int:empresa_id>/relatorio/', views.ConferenciaRelatorioView.as_view(), name='conferencia-relatorio'),
]
