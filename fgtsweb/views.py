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
        else:
            # Usuário comum: mostrar apenas da sua empresa (primeira)
            empresa = Empresa.objects.filter(usuarios=self.request.user).first()
            if empresa:
                funcs_total = Funcionario.objects.filter(empresa=empresa).count()
                lancs_total = Lancamento.objects.filter(empresa=empresa).count()
                lancs_pendentes = Lancamento.objects.filter(empresa=empresa, pago=False).count()
            else:
                funcs_total = lancs_total = lancs_pendentes = 0

        current_plan = PricingPlan.objects.filter(active=True).order_by('sort_order', '-updated_at').first()

        ctx.update({
            'funcs_total': funcs_total,
            'lancs_total': lancs_total,
            'lancs_pendentes': lancs_pendentes,
            'current_plan': current_plan,
            'now': now,
        })
        return ctx
