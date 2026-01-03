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
        # Verificar se é superuser, multi-empresa ou está em trial ativo
        user_has_permission = (
            request.user.is_superuser or 
            getattr(request.user, 'is_multi_empresa', False)
        )
        
        # Se não tem permissão acima, verificar se tem trial ativo
        if not user_has_permission:
            try:
                billing = BillingCustomer.objects.filter(
                    user=request.user, 
                    trial_active=True
                ).first()
                if not billing:
                    return HttpResponseForbidden('Você não tem permissão para criar empresas.')
            except:
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
        
        # Se há plano selecionado, associar à empresa e redirecionar para checkout
        plan_type = self.request.session.get('selected_plan_type')
        if plan_type and self.object:
            try:
                from datetime import date, timedelta
                plan = Plan.objects.get(plan_type=plan_type, active=True)
                # Criar ou atualizar BillingCustomer com trial de 7 dias
                billing, created = BillingCustomer.objects.get_or_create(
                    empresa=self.object,
                    defaults={
                        'plan': plan,
                        'email_cobranca': self.object.email,
                        'status': 'trial',
                        'trial_active': True,
                        'trial_expires': date.today() + timedelta(days=7),
                    }
                )
                if not created and not billing.plan:
                    billing.plan = plan
                    billing.trial_active = True
                    billing.trial_expires = date.today() + timedelta(days=7)
                    billing.status = 'trial'
                    billing.save()
                
                # Limpar da sessão
                if 'selected_plan_type' in self.request.session:
                    del self.request.session['selected_plan_type']
                if 'selected_plan_price' in self.request.session:
                    del self.request.session['selected_plan_price']
                
                messages.success(self.request, f'Empresa criada! Redirecionando para pagamento...')
                
                # Redirecionar para o checkout da empresa
                return redirect('billing-checkout-empresa', empresa_id=self.object.id)
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
