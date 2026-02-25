from django.urls import path
from .views import (
    LancamentoListView, LancamentoCreateView, LancamentoUpdateView, LancamentoDeleteView,
    LancamentoImportView, LancamentoDownloadTemplateView, GerarLancamentosAutomaticosView,
    GerarLancamentosAutomaticosVinculoView, relatorio_por_ids, lancamento_ids,
    RelatorioCompetenciaView, export_relatorio_competencia_csv, export_relatorio_competencia_pdf, download_memoria_calculo
)
from .bulk_delete import LancamentoBulkDeleteView

urlpatterns = [
    path('', LancamentoListView.as_view(), name='lancamento-list'),
    path('novo/', LancamentoCreateView.as_view(), name='lancamento-create'),
    path('<int:pk>/editar/', LancamentoUpdateView.as_view(), name='lancamento-update'),
    path('<int:pk>/excluir/', LancamentoDeleteView.as_view(), name='lancamento-delete'),
    path('importar/', LancamentoImportView.as_view(), name='lancamento-import'),
    path('download-template/', LancamentoDownloadTemplateView.as_view(), name='lancamento-download-template'),
    path('gerar/<int:funcionario_id>/', GerarLancamentosAutomaticosView.as_view(), name='lancamento-gerar-automatico'),
    path('gerar-vinculo/<int:vinculo_id>/', GerarLancamentosAutomaticosVinculoView.as_view(), name='lancamento-gerar-automatico-vinculo'),
    path('ids/', lancamento_ids, name='lancamento-ids'),
    path('relatorio/', RelatorioCompetenciaView.as_view(), name='relatorio-competencia'),
    path('relatorio/por-ids/', relatorio_por_ids, name='relatorio-por-ids'),
    path('relatorio/export/csv', export_relatorio_competencia_csv, name='relatorio-competencia-export-csv'),
    path('relatorio/export/pdf', export_relatorio_competencia_pdf, name='relatorio-competencia-export-pdf'),
    path('relatorio/memoria-calculo', download_memoria_calculo, name='relatorio-memoria-calculo'),
    path('bulk-delete/', LancamentoBulkDeleteView.as_view(), name='lancamento-bulk-delete'),
]
