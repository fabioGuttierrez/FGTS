from django.shortcuts import render, redirect
from django.urls import reverse_lazy
from django.views.generic.edit import CreateView, UpdateView, DeleteView
from django.views.generic.list import ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.http import HttpResponseForbidden
from fgtsweb.mixins import EmpresaScopeMixin, get_allowed_empresa_ids, is_empresa_allowed
from .models import Funcionario
from .forms import FuncionarioForm
from empresas.models import Empresa
from billing.models import BillingCustomer

class FuncionarioCreateView(LoginRequiredMixin, EmpresaScopeMixin, CreateView):
    model = Funcionario
    form_class = FuncionarioForm
    template_name = 'funcionarios/funcionario_form.html'
    success_url = reverse_lazy('funcionario-list')

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        allowed_ids = get_allowed_empresa_ids(self.request.user)
        if allowed_ids is not None:
            form.fields['empresa'].queryset = Empresa.objects.filter(codigo__in=allowed_ids)
        return form

    def form_valid(self, form):
        empresa = form.cleaned_data.get('empresa')
        if empresa and not is_empresa_allowed(self.request.user, empresa.codigo):
            return HttpResponseForbidden('Empresa não permitida para este usuário.')
        funcionario = form.save()
        messages.success(self.request, f'✅ Funcionário "{funcionario.nome}" cadastrado com sucesso!')
        return super().form_valid(form)

class FuncionarioListView(LoginRequiredMixin, EmpresaScopeMixin, ListView):
    model = Funcionario
    template_name = 'funcionarios/funcionario_list.html'
    context_object_name = 'funcionarios'
    paginate_by = 20
    
    def get_queryset(self):
        qs = super().get_queryset().select_related('empresa')
        # Filtra empresas permitidas e com assinatura ativa
        active_empresa_ids = BillingCustomer.objects.filter(status='active').values_list('empresa__codigo', flat=True)
        return self.filter_queryset_by_empresa(qs).filter(empresa__codigo__in=active_empresa_ids)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = FuncionarioForm()
        
        # Contar funcionários ativos e demitidos
        queryset = self.get_queryset()
        context['ativos_count'] = queryset.filter(data_demissao__isnull=True).count()
        context['demitidos_count'] = queryset.filter(data_demissao__isnull=False).count()
        
        return context


class FuncionarioUpdateView(LoginRequiredMixin, EmpresaScopeMixin, UpdateView):
    model = Funcionario
    form_class = FuncionarioForm
    template_name = 'funcionarios/funcionario_form.html'
    success_url = reverse_lazy('funcionario-list')

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        allowed_ids = get_allowed_empresa_ids(self.request.user)
        if allowed_ids is not None:
            form.fields['empresa'].queryset = Empresa.objects.filter(codigo__in=allowed_ids)
        return form

    def get_queryset(self):
        qs = super().get_queryset()
        return self.filter_queryset_by_empresa(qs)

    def form_valid(self, form):
        empresa = form.cleaned_data.get('empresa')
        if empresa and not is_empresa_allowed(self.request.user, empresa.codigo):
            return HttpResponseForbidden('Empresa não permitida para este usuário.')
        funcionario = form.save()
        messages.success(self.request, f'✅ Funcionário "{funcionario.nome}" atualizado com sucesso!')
        return super().form_valid(form)


class FuncionarioDeleteView(LoginRequiredMixin, EmpresaScopeMixin, DeleteView):
    model = Funcionario
    template_name = 'funcionarios/funcionario_confirm_delete.html'
    success_url = reverse_lazy('funcionario-list')

    def get_queryset(self):
        qs = super().get_queryset()
        return self.filter_queryset_by_empresa(qs)

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        nome = self.object.nome
        response = super().delete(request, *args, **kwargs)
        messages.success(request, f'✅ Funcionário "{nome}" excluído com sucesso!')
        return response
