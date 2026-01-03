from typing import Iterable, Optional
from django.db.models import QuerySet
from django.contrib.auth.mixins import UserPassesTestMixin
from django.contrib import messages
from django.shortcuts import redirect


def get_allowed_empresa_ids(user) -> Optional[list]:
    """Return allowed empresa IDs for the user.
    - None means unrestricted (superuser).
    - Empty list means no access.
    """
    if not getattr(user, "is_authenticated", False):
        return []
    if getattr(user, "is_superuser", False):
        return None

    allowed = set()
    if getattr(user, "empresa", None):
        allowed.add(user.empresa.codigo)

    if getattr(user, "is_multi_empresa", False):
        try:
            allowed.update(user.empresas_permitidas.values_list("codigo", flat=True))
        except Exception:
            # If relation not ready yet, ignore
            pass

    return list(allowed)


def is_empresa_allowed(user, empresa_id: int) -> bool:
    allowed = get_allowed_empresa_ids(user)
    if allowed is None:
        return True
    return empresa_id in allowed


def get_active_empresa_ids():
    """Return empresa IDs com billing status ativo ou em trial.
    Se nenhum billing customer existe, retorna todas as empresas."""
    from billing.models import BillingCustomer
    from empresas.models import Empresa
    
    active_billing = BillingCustomer.objects.filter(
        status__in=['active', 'trial']
    ).values_list('empresa__codigo', flat=True)
    
    if active_billing.exists():
        return list(active_billing)
    
    # Se não há clientes de billing, retorna todas as empresas
    return list(Empresa.objects.values_list('codigo', flat=True))


class EmpresaScopeMixin:
    """Mixin to scope querysets by empresa for multi-tenant isolation."""

    def get_allowed_empresa_ids(self) -> Optional[list]:
        return get_allowed_empresa_ids(self.request.user)

    def filter_queryset_by_empresa(self, qs: QuerySet) -> QuerySet:
        allowed = self.get_allowed_empresa_ids()
        if allowed is None:
            return qs
        if not allowed:
            return qs.none()
        model_field_names = {f.name for f in qs.model._meta.fields}
        if "empresa_id" in model_field_names:
            return qs.filter(empresa_id__in=allowed)
        elif "empresa" in model_field_names:
            # Usar lookup direto no campo ForeignKey (por codigo da Empresa)
            return qs.filter(empresa__codigo__in=allowed)
        return qs.none()

    def get_queryset(self):
        qs = super().get_queryset()
        return self.filter_queryset_by_empresa(qs)


# ============ PLAN-BASED AUTHORIZATION MIXINS ============

class PlanFeatureRequiredMixin(UserPassesTestMixin):
    """Verifica se o plano da empresa permite acessar uma feature específica"""
    
    required_feature = None  # Sobrescrever com feature desejada
    
    def test_func(self):
        """Testa se usuário tem acesso à feature"""
        if not self.request.user.is_authenticated:
            return False
        
        try:
            plan = self.request.user.empresa.billing_customer.plan
        except:
            return False
        
        if not plan:
            return False
        
        # Mapear feature para atributo do modelo Plan
        feature_attr = self.get_feature_attribute()
        return getattr(plan, feature_attr, False)
    
    def get_feature_attribute(self):
        """Retorna o atributo do modelo Plan a verificar"""
        return self.required_feature
    
    def handle_no_permission(self):
        """Redireciona com mensagem amigável"""
        plan_name = self.request.user.empresa.billing_customer.plan.get_plan_type_display()
        messages.error(
            self.request,
            f'Este recurso não está disponível no seu plano {plan_name}. '
            f'Faça upgrade para acessá-lo.'
        )
        return redirect('dashboard')


class AdvancedDashboardRequiredMixin(PlanFeatureRequiredMixin):
    """Requer que o plano tenha has_advanced_dashboard=True"""
    required_feature = 'has_advanced_dashboard'


class CustomReportsRequiredMixin(PlanFeatureRequiredMixin):
    """Requer que o plano tenha has_custom_reports=True"""
    required_feature = 'has_custom_reports'


class PDFExportRequiredMixin(PlanFeatureRequiredMixin):
    """Requer que o plano tenha has_pdf_export=True"""
    required_feature = 'has_pdf_export'


class APIAccessRequiredMixin(PlanFeatureRequiredMixin):
    """Requer que o plano tenha has_api=True"""
    required_feature = 'has_api'

