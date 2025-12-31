from django.shortcuts import render
from django.http import HttpResponseForbidden
from django.urls import reverse_lazy
from django.views.generic.edit import CreateView
from django.views.generic.list import ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from fgtsweb.mixins import EmpresaScopeMixin
from .models import Empresa
from .forms import EmpresaForm

class EmpresaCreateView(LoginRequiredMixin, CreateView):
    model = Empresa
    form_class = EmpresaForm
    template_name = 'empresas/empresa_form.html'
    success_url = reverse_lazy('empresa-list')

    def dispatch(self, request, *args, **kwargs):
        # Somente superuser ou gestor multiempresas pode criar novas empresas
        if not (request.user.is_superuser or getattr(request.user, 'is_multi_empresa', False)):
            return HttpResponseForbidden('Você não tem permissão para criar empresas.')
        return super().dispatch(request, *args, **kwargs)

class EmpresaListView(LoginRequiredMixin, EmpresaScopeMixin, ListView):
    model = Empresa
    template_name = 'empresas/empresa_list.html'
    context_object_name = 'empresas'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = EmpresaForm()
        return context
