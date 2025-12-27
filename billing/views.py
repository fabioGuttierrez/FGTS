from datetime import timedelta
from decimal import Decimal
from django.contrib import messages
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from empresas.models import Empresa
from .models import BillingCustomer, Subscription, Payment, PricingPlan
from .services.asaas_client import AsaasClient


DEFAULT_PLAN_VALUE = Decimal('99.90')
DEFAULT_PERIODICITY = 'MONTHLY'


def _get_current_plan():
    plan = PricingPlan.objects.filter(active=True).order_by('sort_order', '-updated_at').first()
    return plan


def _ensure_billing_customer(empresa: Empresa, email_fallback: str = None) -> BillingCustomer:
    billing, _ = BillingCustomer.objects.get_or_create(
        empresa=empresa,
        defaults={
            'email_cobranca': email_fallback,
            'status': 'pending',
        }
    )
    if email_fallback and not billing.email_cobranca:
        billing.email_cobranca = email_fallback
        billing.save(update_fields=['email_cobranca'])
    return billing


def _first_email(empresa: Empresa) -> str:
    if empresa.email:
        return empresa.email
    if empresa.nome_contato:
        return None  # prefer blank than wrong email
    return None


def checkout_empresa(request, empresa_id):
    if request.method != 'POST':
        return HttpResponseBadRequest('Use POST para iniciar checkout.')

    empresa = get_object_or_404(Empresa, pk=empresa_id)
    billing_customer = _ensure_billing_customer(empresa, email_fallback=_first_email(empresa))

    try:
        client = AsaasClient()
    except ValueError as exc:
        messages.error(request, str(exc))
        return HttpResponseRedirect('/')

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

    plan = _get_current_plan()
    amount = plan.amount if plan else DEFAULT_PLAN_VALUE
    periodicity = plan.periodicity if plan else DEFAULT_PERIODICITY

    # Cria assinatura padrão e primeiro pagamento
    due_date = timezone.now().date() + timedelta(days=3)
    subscription_payload = {
        'customer': billing_customer.asaas_customer_id,
        'billingType': 'BOLETO',
        'value': float(amount),
        'cycle': periodicity,
        'description': plan.description if plan and plan.description else 'Assinatura FGTS Web',
    }
    subscription_resp = client.create_subscription(subscription_payload)
    subscription = Subscription.objects.create(
        customer=billing_customer,
        asaas_subscription_id=subscription_resp.get('id'),
        plan_name='Plano FGTS Web',
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
