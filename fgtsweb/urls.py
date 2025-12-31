"""
URL configuration for fgtsweb project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView
from django.contrib.auth import views as auth_views
from empresas.views import EmpresaCreateView, EmpresaListView
from funcionarios.views import FuncionarioCreateView, FuncionarioListView
from lancamentos.views import (
    RelatorioCompetenciaView, 
    export_relatorio_competencia_csv, 
    export_relatorio_competencia_pdf,
    download_memoria_calculo
)
from indices.views import IndiceListView
from coefjam.views import CoefJamListView
from configuracoes.views import ConfiguracaoListView
from .views import DashboardView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', TemplateView.as_view(template_name='landing.html'), name='home'),
    path('login/', auth_views.LoginView.as_view(template_name='auth/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='home'), name='logout'),
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('billing/', include('billing.urls')),
    path('empresas/', EmpresaListView.as_view(), name='empresa-list'),
    path('empresas/novo/', EmpresaCreateView.as_view(), name='empresa-create'),
    path('funcionarios/', FuncionarioListView.as_view(), name='funcionario-list'),
    path('funcionarios/novo/', FuncionarioCreateView.as_view(), name='funcionario-create'),
    path('lancamentos/relatorio/', RelatorioCompetenciaView.as_view(), name='relatorio-competencia'),
    path('lancamentos/relatorio/export/csv', export_relatorio_competencia_csv, name='relatorio-competencia-export-csv'),
    path('lancamentos/relatorio/export/pdf', export_relatorio_competencia_pdf, name='relatorio-competencia-export-pdf'),
    path('lancamentos/relatorio/memoria-calculo', download_memoria_calculo, name='relatorio-memoria-calculo'),
    path('indices/', IndiceListView.as_view(), name='indice-list'),
    path('coefjam/', CoefJamListView.as_view(), name='coefjam-list'),
    path('configuracoes/', ConfiguracaoListView.as_view(), name='configuracao-list'),
]
