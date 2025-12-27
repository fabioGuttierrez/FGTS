from django.shortcuts import render, redirect
from django.urls import reverse_lazy
from django.views.generic.edit import CreateView, UpdateView, DeleteView
from django.views.generic.list import ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from .models import Funcionario
from .forms import FuncionarioForm
from empresas.models import Empresa
from billing.models import BillingCustomer

class FuncionarioCreateView(LoginRequiredMixin, CreateView):
    model = Funcionario
    form_class = FuncionarioForm
    template_name = 'funcionarios/funcionario_form.html'
    success_url = reverse_lazy('funcionario-list')

class FuncionarioListView(LoginRequiredMixin, ListView):
    model = Funcionario
    template_name = 'funcionarios/funcionario_list.html'
    context_object_name = 'funcionarios'
    paginate_by = 20
    
    def get_queryset(self):
        qs = super().get_queryset().select_related('empresa')
        # Exibir somente funcionários de empresas com assinatura ativa
        active_empresa_ids = BillingCustomer.objects.filter(status='active').values_list('empresa_id', flat=True)
        return qs.filter(empresa_id__in=active_empresa_ids)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = FuncionarioForm()
        return context
