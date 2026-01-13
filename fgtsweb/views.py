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

        # Se superuser/staff, mostrar dados globais; senão, apenas da empresa do usuário
        if self.request.user.is_superuser or self.request.user.is_staff:
            funcs_total = Funcionario.objects.count()
            lancs_total = Lancamento.objects.count()
            lancs_pendentes = Lancamento.objects.filter(pago=False).count()
            empresa = None
            billing_customer = None
        else:
            # Usuário comum: buscar empresa associada
            empresa = None
            billing_customer = None
            
            # Tentar primeiro a empresa principal do usuário (verificar ID antes)
            if self.request.user.empresa_id:
                try:
                    # Buscar empresa pelo código/ID
                    empresa = Empresa.objects.get(pk=self.request.user.empresa_id)
                except (Empresa.DoesNotExist, Exception):
                    empresa = None
            
            # Se não tem empresa principal, tenta as empresas permitidas
            if not empresa:
                try:
                    empresa = self.request.user.empresas_permitidas.first()
                except Exception:
                    empresa = None
            
            if empresa:
                funcs_total = Funcionario.objects.filter(empresa=empresa).count()
                lancs_total = Lancamento.objects.filter(empresa=empresa).count()
                lancs_pendentes = Lancamento.objects.filter(empresa=empresa, pago=False).count()
                # Buscar informações de billing/trial através da empresa
                try:
                    billing_customer = BillingCustomer.objects.filter(empresa=empresa).first()
                except Exception:
                    billing_customer = None
            else:
                funcs_total = lancs_total = lancs_pendentes = 0
                billing_customer = None

        # Definir plano atual baseado em billing_customer
        current_plan = None
        if billing_customer:
            current_plan = billing_customer.plan
        else:
            # Fallback para plano padrão ativo
            current_plan = PricingPlan.objects.filter(active=True).order_by('sort_order', '-updated_at').first()

        ctx.update({
            'funcs_total': funcs_total,
            'lancs_total': lancs_total,
            'lancs_pendentes': lancs_pendentes,
            'empresa': empresa,
            'billing_customer': billing_customer,
            'current_plan': current_plan,
            'now': now,
        })
        return ctx
