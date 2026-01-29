from datetime import timedelta
from decimal import Decimal
from typing import Optional
import logging

import requests
from requests import RequestException
from django.contrib import messages
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import TemplateView

from empresas.models import Empresa
from fgtsweb.mixins import is_empresa_allowed
from .models import BillingCustomer, Subscription, Payment, PricingPlan, Plan
from .services.asaas_client import AsaasClient

logger = logging.getLogger(__name__)


DEFAULT_PLAN_VALUE = Decimal('99.90')
DEFAULT_PERIODICITY = 'MONTHLY'
PLAN_PRICE_OVERRIDE = {
    'BASIC': Decimal('199.00'),          # Essencial
    'PROFESSIONAL': Decimal('699.00'),   # Profissional
    'ENTERPRISE': Decimal('0.00'),       # Sob consulta
}


class CheckoutPlanoView(TemplateView):
    """Página de checkout pública - sem login obrigatório"""
    template_name = 'billing/checkout_plano.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        plan_type = self.kwargs.get('plan_type')
        
        # Buscar plano selecionado (se houver)
        if plan_type:
            try:
                context['selected_plan'] = Plan.objects.get(plan_type=plan_type, active=True)
            except Plan.DoesNotExist:
                context['selected_plan'] = None
        
        # Listar todos os planos
        context['all_plans'] = Plan.objects.filter(active=True).order_by('plan_type')
        
        return context
    
    def post(self, request, *args, **kwargs):
        """Processa seleção e redireciona"""
        plan_type = request.POST.get('plan_type')
        
        try:
            plan = Plan.objects.get(plan_type=plan_type, active=True)
        except Plan.DoesNotExist:
            messages.error(request, 'Plano inválido')
            return redirect('billing:checkout-plano')
        
        # Aplicar override de preço conforme tabela pública
        plan_price = PLAN_PRICE_OVERRIDE.get(plan.plan_type, plan.price_monthly)
        
        # Salvar na sessão
        request.session['selected_plan_type'] = plan_type
        request.session['selected_plan_price'] = str(plan_price)
        
        # Se logado, ir direto para criar empresa
        if request.user.is_authenticated:
            empresa = getattr(request.user, 'empresa', None)
            if not empresa and hasattr(request.user, 'empresas_permitidas'):
                empresa = request.user.empresas_permitidas.first()
            if empresa:
                return redirect('billing:billing-checkout-empresa', empresa.pk)
            return redirect('empresa-create')
        
        # Se não logado, ir para registro/login (com next setado)
        messages.info(request, f'Você selecionou o plano {plan.get_plan_type_display()}. Crie uma conta para continuar.')
        return redirect('register')


def _get_current_plan():
    """Busca o plano ativo mais recente da tabela PricingPlan."""
    return PricingPlan.objects.filter(active=True).order_by('sort_order', '-updated_at').first()


def _ensure_billing_customer(empresa: Empresa, email_fallback: Optional[str] = None) -> BillingCustomer:
    """Garante registro de billing para a empresa, preenchendo email se vazio."""
    billing, _ = BillingCustomer.objects.get_or_create(
        empresa=empresa,
        defaults={'email_cobranca': email_fallback, 'status': 'pending'},
    )

    if not billing.email_cobranca and email_fallback:
        billing.email_cobranca = email_fallback
        billing.save(update_fields=['email_cobranca'])

    return billing


def _first_email(empresa: Empresa) -> Optional[str]:
    if getattr(empresa, 'email', None):
        return empresa.email
    # Evita usar email genérico incorreto
    return None


def _resolve_plan_choice(
    request,
    billing_customer: BillingCustomer,
    persist_choice: bool = False,
    clear_session: bool = False,
):
    """Determina plano/valor usando sessão, plano salvo ou PricingPlan.

    - Usa seleção da sessão se presente (landing checkout)
    - Caso contrário, usa plano já vinculado ao billing_customer
    - Em último caso, usa PricingPlan ativo ou defaults
    - persist_choice: salva plano no billing_customer quando possível
    - clear_session: remove seleção da sessão após uso
    """

    selected_plan_type = request.session.get('selected_plan_type')
    selected_plan_price = request.session.get('selected_plan_price')

    plan_obj = None
    amount = DEFAULT_PLAN_VALUE
    periodicity = DEFAULT_PERIODICITY
    plan_name = 'Plano FGTS Web'

    if selected_plan_type:
        try:
            plan_obj = Plan.objects.get(plan_type=selected_plan_type, active=True)
            amount = PLAN_PRICE_OVERRIDE.get(plan_obj.plan_type, plan_obj.price_monthly)
            periodicity = 'MONTHLY'
            plan_name = f"Plano {plan_obj.get_plan_type_display()}"
            if persist_choice and billing_customer.plan_id != plan_obj.id:
                billing_customer.plan = plan_obj
                billing_customer.save(update_fields=['plan'])
        except Plan.DoesNotExist:
            if selected_plan_price:
                try:
                    amount = Decimal(selected_plan_price)
                except Exception:
                    amount = DEFAULT_PLAN_VALUE
            periodicity = 'MONTHLY'
            type_label = dict(Plan.PLAN_TYPES).get(selected_plan_type, selected_plan_type)
            plan_name = f"Plano {type_label}"

    if not plan_obj and billing_customer.plan:
        plan_obj = billing_customer.plan
        amount = PLAN_PRICE_OVERRIDE.get(plan_obj.plan_type, plan_obj.price_monthly)
        periodicity = 'MONTHLY'
        plan_name = f"Plano {plan_obj.get_plan_type_display()}"

    if not plan_obj:
        pricing_plan = _get_current_plan()
        if pricing_plan:
            amount = pricing_plan.amount
            periodicity = pricing_plan.periodicity
            plan_name = pricing_plan.description or pricing_plan.name or plan_name

    if clear_session:
        request.session.pop('selected_plan_type', None)
        request.session.pop('selected_plan_price', None)

    return plan_obj, amount, periodicity, plan_name


def checkout_empresa(request, empresa_id):
    empresa = get_object_or_404(Empresa, pk=empresa_id)

    # Escopo multi-tenant: usuário precisa ter permissão para esta empresa
    if not is_empresa_allowed(request.user, empresa.codigo):
        return HttpResponseBadRequest('Empresa não permitida para este usuário.')
    
    # Se GET, mostrar página de confirmação
    if request.method == 'GET':
        billing_customer = _ensure_billing_customer(empresa, email_fallback=_first_email(empresa))
        _, amount, periodicity, plan_name = _resolve_plan_choice(
            request,
            billing_customer,
            persist_choice=False,
            clear_session=False,
        )
        context = {
            'empresa': empresa,
            'billing_customer': billing_customer,
            'plan_name': plan_name,
            'amount': amount,
            'periodicity': periodicity,
        }
        return render(request, 'billing/checkout_empresa.html', context)
    
    # Se POST, processar pagamento
    if request.method != 'POST':
        return HttpResponseBadRequest('Método não suportado.')

    billing_customer = _ensure_billing_customer(empresa, email_fallback=_first_email(empresa))

    try:
        client = AsaasClient()

        # Cria cliente no Asaas se ainda não existir
        if not billing_customer.asaas_customer_id:
            customer_payload = {
                'name': empresa.nome,
                'cpfCnpj': empresa.cnpj or '',
                'email': billing_customer.email_cobranca,
                'phone': empresa.fone_contato,
                'mobilePhone': empresa.fone_contato,
                'externalReference': str(empresa.pk),
            }
            created_customer = client.create_customer(customer_payload)
            billing_customer.asaas_customer_id = created_customer.get('id')
            billing_customer.status = 'pending'
            billing_customer.save(update_fields=['asaas_customer_id', 'status'])

        # Determinar plano e valor
        plan_obj, amount, periodicity, plan_name = _resolve_plan_choice(
            request,
            billing_customer,
            persist_choice=True,
            clear_session=True,
        )

        # Cria assinatura padrão e primeiro pagamento
        due_date = timezone.now().date() + timedelta(days=3)
        subscription_payload = {
            'customer': billing_customer.asaas_customer_id,
            'billingType': 'BOLETO',
            'value': float(amount),
            'cycle': periodicity,
            'description': plan_name,
        }
        subscription_resp = client.create_subscription(subscription_payload)
        subscription = Subscription.objects.create(
            customer=billing_customer,
            asaas_subscription_id=subscription_resp.get('id'),
            plan_name=plan_name,
            amount=amount,
            periodicity=periodicity,
            status='pending',
            next_due_date=due_date,
        )

        payment_payload = {
            'customer': billing_customer.asaas_customer_id,
            'billingType': 'BOLETO',
            'value': float(amount),
            'dueDate': due_date.isoformat(),
            'description': '1a mensalidade FGTS Web',
            'subscription': subscription_resp.get('id'),
        }
        payment_resp = client.create_payment(payment_payload)

        Payment.objects.create(
            subscription=subscription,
            asaas_payment_id=payment_resp.get('id'),
            amount=amount,
            due_date=due_date,
            status=payment_resp.get('status', 'pending'),
            invoice_url=payment_resp.get('invoiceUrl') or payment_resp.get('bankSlipUrl'),
        )

        redirect_url = payment_resp.get('invoiceUrl') or payment_resp.get('bankSlipUrl')
        if redirect_url:
            return HttpResponseRedirect(redirect_url)

        return JsonResponse({'subscriptionId': subscription_resp.get('id'), 'paymentId': payment_resp.get('id')})

    except RequestException as exc:
        status = exc.response.status_code if getattr(exc, 'response', None) is not None else '?'
        detail = ''
        if getattr(exc, 'response', None) is not None:
            try:
                detail = exc.response.json()
            except Exception:
                detail = exc.response.text
        messages.error(request, f'Erro ao integrar com Asaas ({status}): {detail}')
        logger.exception('Erro na integração Asaas durante checkout_empresa')
        return HttpResponseRedirect(request.path)
    except Exception:
        logger.exception('Erro inesperado no checkout_empresa')
        messages.error(request, 'Erro inesperado ao processar pagamento. Tente novamente ou fale com o suporte.')
        return HttpResponseRedirect(request.path)


@csrf_exempt
def asaas_webhook(request):
    if request.method != 'POST':
        return HttpResponseBadRequest('Método não suportado')

    try:
        data = request.json if hasattr(request, 'json') else None
    except Exception:
        data = None
    if data is None:
        import json
        try:
            data = json.loads(request.body.decode('utf-8'))
        except Exception:
            return HttpResponseBadRequest('JSON inválido')

    event = data.get('event') if isinstance(data, dict) else None
    payment_data = data.get('payment') if isinstance(data, dict) else None

    if not event or not payment_data:
        return HttpResponseBadRequest('Payload incompleto')

    asaas_payment_id = payment_data.get('id')
    status = payment_data.get('status')
    paid_at = payment_data.get('paymentDate')

    try:
        payment = Payment.objects.select_related('subscription__customer').get(asaas_payment_id=asaas_payment_id)
    except Payment.DoesNotExist:
        return HttpResponse('Pagamento não encontrado', status=200)

    # Atualiza status do pagamento e assinatura
    payment.status = status if status in dict(Payment.STATUS_CHOICES) else payment.status
    if paid_at:
        try:
            payment.pay_date = timezone.datetime.fromisoformat(paid_at).date()
        except Exception:
            pass
    payment.save()

    subscription = payment.subscription
    if status in ['RECEIVED', 'CONFIRMED', 'CONFIRMED_OVERDUE']:
        subscription.status = 'active'
        subscription.save(update_fields=['status'])
    elif status in ['OVERDUE']:
        subscription.status = 'overdue'
        subscription.save(update_fields=['status'])
    elif status in ['CANCELLED', 'REFUNDED']:
        subscription.status = 'canceled'
        subscription.save(update_fields=['status'])

    billing_customer = subscription.customer
    if subscription.status == 'active':
        billing_customer.status = 'active'
    elif subscription.status in ['overdue', 'canceled']:
        billing_customer.status = 'pending'
    billing_customer.save(update_fields=['status'])

    return HttpResponse('OK')

# ===== FEEDBACK =====
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import CreateView, ListView
from .models import Feedback
from .forms import FeedbackForm
from fgtsweb.mixins import EmpresaScopeMixin


class FeedbackCreateView(LoginRequiredMixin, EmpresaScopeMixin, CreateView):
    """Criar novo feedback/sugestão/reclamação"""
    model = Feedback
    form_class = FeedbackForm
    template_name = 'billing/feedback_form.html'
    
    def form_valid(self, form):
        # Descobrir a empresa do usuário (multi-tenant seguro)
        # 1) empresa principal do usuário
        empresa_user = getattr(self.request.user, 'empresa', None)
        # 2) primeira empresa permitida (caso multiempresa)
        empresa_permitida = (
            self.request.user.empresas_permitidas.all().first()
            if hasattr(self.request.user, 'empresas_permitidas') else None
        )

        empresa = empresa_user or empresa_permitida

        if not empresa:
            messages.error(self.request, 'Você não tem empresa associada.')
            return redirect('dashboard')

        # Garantir escopo permitido
        if not is_empresa_allowed(self.request.user, empresa.codigo):
            messages.error(self.request, 'Empresa não permitida para este usuário.')
            return redirect('dashboard')

        form.instance.empresa = empresa
        
        response = super().form_valid(form)
        messages.success(self.request, '✅ Feedback enviado com sucesso! Obrigado pelas sugestões.')
        return response
    
    def get_success_url(self):
        return reverse('dashboard')


class FeedbackListView(LoginRequiredMixin, ListView):
    """Listar feedbacks do usuário (admin)"""
    model = Feedback
    template_name = 'billing/feedback_list.html'
    context_object_name = 'feedbacks'
    paginate_by = 20
    
    def get_queryset(self):
        if self.request.user.is_staff:
            return Feedback.objects.all()
        return Feedback.objects.none()