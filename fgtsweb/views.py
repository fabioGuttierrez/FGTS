from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView
from django.utils import timezone

from empresas.models import Empresa
from funcionarios.models import Funcionario
from lancamentos.models import Lancamento
from indices.models import Indice
from coefjam.models import CoefJam
from billing.models import BillingCustomer, Subscription, Payment, PricingPlan


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        now = timezone.now()

        empresas_total = Empresa.objects.count()
        funcs_total = Funcionario.objects.count()
        lancs_total = Lancamento.objects.count()
        lancs_pendentes = Lancamento.objects.filter(pago=False).count()

        billing_active = BillingCustomer.objects.filter(status='active').count()
        billing_pending = BillingCustomer.objects.filter(status='pending').count()
        billing_canceled = BillingCustomer.objects.filter(status='canceled').count()

        last_indice = Indice.objects.order_by('-data_indice').first()
        last_jam = CoefJam.objects.order_by('-data_pagamento').first()

        current_plan = PricingPlan.objects.filter(active=True).order_by('sort_order', '-updated_at').first()

        ctx.update({
            'empresas_total': empresas_total,
            'funcs_total': funcs_total,
            'lancs_total': lancs_total,
            'lancs_pendentes': lancs_pendentes,
            'billing_active': billing_active,
            'billing_pending': billing_pending,
            'billing_canceled': billing_canceled,
            'last_indice': last_indice,
            'last_jam': last_jam,
            'current_plan': current_plan,
            'now': now,
        })
        return ctx
