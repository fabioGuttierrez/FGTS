from django.db import models
from django.utils import timezone
from empresas.models import Empresa
from django.core.validators import MinValueValidator


class Plan(models.Model):
    """Planos de assinatura: Básico, Profissional, Empresarial"""
    
    PLAN_TYPES = [
        ('BASIC', 'Básico'),
        ('PROFESSIONAL', 'Profissional'),
        ('ENTERPRISE', 'Empresarial'),
    ]
    
    SUPPORT_LEVELS = [
        ('EMAIL', 'E-mail'),
        ('PRIORITY', 'Prioritário'),
        ('24_7', '24/7'),
    ]
    
    plan_type = models.CharField(
        max_length=20,
        choices=PLAN_TYPES,
        unique=True,
        verbose_name='Tipo de Plano'
    )
    max_employees = models.IntegerField(
        null=True,
        blank=True,
        verbose_name='Máximo de Colaboradores',
        help_text='Deixe em branco para ilimitado'
    )
    
    # Features
    has_advanced_dashboard = models.BooleanField(
        default=False,
        verbose_name='Dashboard Avançado'
    )
    has_custom_reports = models.BooleanField(
        default=False,
        verbose_name='Relatórios Personalizados'
    )
    has_pdf_export = models.BooleanField(
        default=False,
        verbose_name='Exportar PDF/Excel'
    )
    has_api = models.BooleanField(
        default=False,
        verbose_name='API Access'
    )
    
    # Support
    support_level = models.CharField(
        max_length=20,
        choices=SUPPORT_LEVELS,
        default='EMAIL',
        verbose_name='Nível de Suporte'
    )
    
    # Pricing
    price_monthly = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name='Preço Mensal'
    )
    price_yearly = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name='Preço Anual'
    )
    
    # Meta
    active = models.BooleanField(default=True, verbose_name='Ativo')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['plan_type']
        verbose_name = 'Plano'
        verbose_name_plural = 'Planos'
    
    def __str__(self):
        return f"{self.get_plan_type_display()}"
    
    def can_add_employee(self, current_count):
        """Verifica se é possível adicionar mais um colaborador"""
        if self.max_employees is None:  # Ilimitado
            return True
        return current_count < self.max_employees
    
    def get_usage_percentage(self, current_count):
        """Retorna percentual de uso do plano"""
        if self.max_employees is None:
            return 0
        return (current_count / self.max_employees) * 100


class BillingCustomer(models.Model):
    STATUS_CHOICES = [
        ('active', 'Ativo'),
        ('inactive', 'Inativo'),
        ('pending', 'Pendente'),
        ('canceled', 'Cancelado'),
    ]

    empresa = models.OneToOneField(Empresa, on_delete=models.CASCADE, related_name='billing_customer')
    plan = models.ForeignKey(Plan, on_delete=models.SET_NULL, null=True, blank=True, related_name='customers', verbose_name='Plano')
    active_employees = models.IntegerField(default=0, verbose_name='Colaboradores Ativos')
    email_cobranca = models.EmailField(blank=True, null=True)
    asaas_customer_id = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.empresa.nome} ({self.get_status_display()})"
    
    def can_add_employee(self):
        """Verifica se é possível adicionar outro colaborador no plano atual"""
        if not self.plan:
            return False
        return self.plan.can_add_employee(self.active_employees)
    
    def get_usage_percentage(self):
        """Retorna percentual de uso do plano"""
        if not self.plan:
            return 0
        return self.plan.get_usage_percentage(self.active_employees)
    
    def get_employees_remaining(self):
        """Retorna quantos colaboradores ainda podem ser adicionados"""
        if not self.plan or self.plan.max_employees is None:
            return None  # Ilimitado
        return self.plan.max_employees - self.active_employees


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
