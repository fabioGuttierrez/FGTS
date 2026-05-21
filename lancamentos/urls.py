from django.urls import path
from .views import (
    LancamentoListView, LancamentoCreateView, LancamentoUpdateView, LancamentoDeleteView,
    LancamentoImportView, LancamentoDownloadTemplateView,
    RelatorioCompetenciaView, relatorio_por_ids, lancamento_ids,
    export_relatorio_competencia_csv, export_relatorio_competencia_pdf, download_memoria_calculo,
    RelatorioRecolhimentoFuncionarioView, export_recolhimento_funcionario_pdf,
    export_recolhimento_funcionario_xlsx,
    LancamentoImportStatusView, lancamento_import_status_json,
    LancamentoImportPreviewView, LancamentoImportConfirmView,
)
from .views_re_extrato import (
    REImportView, REImportPreviewView, REImportConfirmView,
    REImportStatusView, re_import_status_json,
    ExtratoImportView, ExtratoImportPreviewView, ExtratoImportConfirmView,
    ExtratoImportStatusView, extrato_import_status_json,
)
from .bulk_delete import LancamentoBulkDeleteView

urlpatterns = [
    path('', LancamentoListView.as_view(), name='lancamento-list'),
    path('novo/', LancamentoCreateView.as_view(), name='lancamento-create'),
    path('<int:pk>/editar/', LancamentoUpdateView.as_view(), name='lancamento-update'),
    path('<int:pk>/excluir/', LancamentoDeleteView.as_view(), name='lancamento-delete'),
    path('importar/', LancamentoImportView.as_view(), name='lancamento-import'),
    path('importar/<int:pk>/preview/', LancamentoImportPreviewView.as_view(), name='lancamento-import-preview'),
    path('importar/<int:pk>/confirmar/', LancamentoImportConfirmView.as_view(), name='lancamento-import-confirm'),
    path('importar/<int:pk>/status/', LancamentoImportStatusView.as_view(), name='lancamento-import-status'),
    path('importar/<int:pk>/status/json/', lancamento_import_status_json, name='lancamento-import-status-json'),
    path('download-template/', LancamentoDownloadTemplateView.as_view(), name='lancamento-download-template'),
    path('ids/', lancamento_ids, name='lancamento-ids'),
    path('relatorio/', RelatorioCompetenciaView.as_view(), name='relatorio-competencia'),
    path('relatorio/por-ids/', relatorio_por_ids, name='relatorio-por-ids'),
    path('relatorio/export/csv', export_relatorio_competencia_csv, name='relatorio-competencia-export-csv'),
    path('relatorio/export/pdf', export_relatorio_competencia_pdf, name='relatorio-competencia-export-pdf'),
    path('relatorio/memoria-calculo', download_memoria_calculo, name='relatorio-memoria-calculo'),
    path('relatorio/recolhimento-funcionario/', RelatorioRecolhimentoFuncionarioView.as_view(), name='recolhimento-funcionario'),
    path('relatorio/recolhimento-funcionario/pdf', export_recolhimento_funcionario_pdf, name='recolhimento-funcionario-pdf'),
    path('relatorio/recolhimento-funcionario/xlsx', export_recolhimento_funcionario_xlsx, name='recolhimento-funcionario-xlsx'),
    path('bulk-delete/', LancamentoBulkDeleteView.as_view(), name='lancamento-bulk-delete'),

    # Importador RE / SEFIP
    path('importar-re/', REImportView.as_view(), name='re-import'),
    path('importar-re/<int:pk>/preview/', REImportPreviewView.as_view(), name='re-import-preview'),
    path('importar-re/<int:pk>/confirmar/', REImportConfirmView.as_view(), name='re-import-confirm'),
    path('importar-re/<int:pk>/status/', REImportStatusView.as_view(), name='re-import-status'),
    path('importar-re/<int:pk>/status/json/', re_import_status_json, name='re-import-status-json'),

    # Importador Extrato Analítico CEF
    path('importar-extrato/', ExtratoImportView.as_view(), name='extrato-import'),
    path('importar-extrato/<int:pk>/preview/', ExtratoImportPreviewView.as_view(), name='extrato-import-preview'),
    path('importar-extrato/<int:pk>/confirmar/', ExtratoImportConfirmView.as_view(), name='extrato-import-confirm'),
    path('importar-extrato/<int:pk>/status/', ExtratoImportStatusView.as_view(), name='extrato-import-status'),
    path('importar-extrato/<int:pk>/status/json/', extrato_import_status_json, name='extrato-import-status-json'),
]
