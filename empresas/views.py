from django.shortcuts import render, redirect
from django.http import HttpResponseForbidden
from django.urls import reverse_lazy
from django.views.generic.edit import CreateView
from django.views.generic.list import ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from fgtsweb.mixins import EmpresaScopeMixin
from .models import Empresa
from .forms import EmpresaForm
from billing.models import Plan, BillingCustomer


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
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Passar plano selecionado se houver na sessão
        plan_type = self.request.session.get('selected_plan_type')
        if plan_type:
            try:
                context['selected_plan'] = Plan.objects.get(plan_type=plan_type, active=True)
            except Plan.DoesNotExist:
                pass
        return context
    
    def form_valid(self, form):
        response = super().form_valid(form)
        
        # Se há plano selecionado, associar à empresa
        plan_type = self.request.session.get('selected_plan_type')
        if plan_type and self.object:
            try:
                plan = Plan.objects.get(plan_type=plan_type, active=True)
                # Criar ou atualizar BillingCustomer com o plano
                billing, created = BillingCustomer.objects.get_or_create(
                    empresa=self.object,
                    defaults={
                        'plan': plan,
                        'email_cobranca': self.object.email,
                        'status': 'pending',
                    }
                )
                if not created and not billing.plan:
                    billing.plan = plan
                    billing.save()
                
                # Limpar da sessão
                del self.request.session['selected_plan_type']
                del self.request.session['selected_plan_price']
                
                messages.success(self.request, f'Empresa criada! Plano {plan.get_plan_type_display()} atribuído.')
            except Plan.DoesNotExist:
                pass
        
        return response

class EmpresaListView(LoginRequiredMixin, EmpresaScopeMixin, ListView):
    model = Empresa
    template_name = 'empresas/empresa_list.html'
    context_object_name = 'empresas'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = EmpresaForm()
        return context
