from django.db import models
from django.utils import timezone
from empresas.models import Empresa
from django.core.validators import MinValueValidator


class BillingCustomer(models.Model):
    STATUS_CHOICES = [
        ('active', 'Ativo'),
        ('inactive', 'Inativo'),
        ('pending', 'Pendente'),
        ('canceled', 'Cancelado'),
    ]

    empresa = models.OneToOneField(Empresa, on_delete=models.CASCADE, related_name='billing_customer')
    email_cobranca = models.EmailField(blank=True, null=True)
    asaas_customer_id = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.empresa.nome} ({self.get_status_display()})"


class PricingPlan(models.Model):
    PERIODICITY_CHOICES = [
        ('MONTHLY', 'Mensal'),
        ('YEARLY', 'Anual'),
    ]

    name = models.CharField(max_length=120, default='Plano FGTS Web')
    description = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    periodicity = models.CharField(max_length=10, choices=PERIODICITY_CHOICES, default='MONTHLY')
    active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', '-updated_at']

    def __str__(self):
        return f"{self.name} ({self.get_periodicity_display()})"


class Subscription(models.Model):
    PERIODICITY_CHOICES = [
        ('MONTHLY', 'Mensal'),
        ('YEARLY', 'Anual'),
    ]

    STATUS_CHOICES = [
        ('active', 'Ativa'),
        ('pending', 'Pendente'),
        ('overdue', 'Em atraso'),
        ('canceled', 'Cancelada'),
        ('suspended', 'Suspensa'),
    ]

    customer = models.ForeignKey(BillingCustomer, on_delete=models.CASCADE, related_name='subscriptions')
    asaas_subscription_id = models.CharField(max_length=100, blank=True, null=True)
    plan_name = models.CharField(max_length=120, default='Plano FGTS Web')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    periodicity = models.CharField(max_length=10, choices=PERIODICITY_CHOICES, default='MONTHLY')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    next_due_date = models.DateField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.plan_name} - {self.customer.empresa.nome}"


class Payment(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pendente'),
        ('confirmed', 'Confirmado'),
        ('overdue', 'Em atraso'),
        ('canceled', 'Cancelado'),
    ]

    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name='payments')
    asaas_payment_id = models.CharField(max_length=100, blank=True, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    due_date = models.DateField()
    pay_date = models.DateField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    invoice_url = models.URLField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.subscription.customer.empresa.nome} - {self.amount} ({self.get_status_display()})"
