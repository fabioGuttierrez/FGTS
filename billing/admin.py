from django.contrib import admin
from .models import Plan, BillingCustomer, Subscription, Payment, PricingPlan


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('get_plan_type_display', 'max_employees', 'support_level', 'price_monthly', 'active')
    list_filter = ('plan_type', 'support_level', 'active')
    search_fields = ('plan_type',)
    fieldsets = (
        ('Tipo de Plano', {
            'fields': ('plan_type', 'max_employees', 'active')
        }),
        ('Features', {
            'fields': (
                'has_advanced_dashboard',
                'has_custom_reports',
                'has_pdf_export',
                'has_api',
            )
        }),
        ('Suporte', {
            'fields': ('support_level',)
        }),
        ('Preços', {
            'fields': ('price_monthly', 'price_yearly')
        }),
    )
    readonly_fields = ('created_at', 'updated_at')
    
    def get_plan_type_display(self, obj):
        return obj.get_plan_type_display()
    get_plan_type_display.short_description = 'Plano'


@admin.register(BillingCustomer)
class BillingCustomerAdmin(admin.ModelAdmin):
    list_display = ('empresa', 'plan', 'active_employees', 'status', 'created_at')
    list_filter = ('plan', 'status')
    search_fields = ('empresa__nome', 'asaas_customer_id')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Empresa e Plano', {
            'fields': ('empresa', 'plan', 'active_employees')
        }),
        ('Cobrança', {
            'fields': ('email_cobranca', 'status', 'asaas_customer_id')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('customer', 'plan_name', 'amount', 'periodicity', 'status', 'next_due_date', 'asaas_subscription_id')
    search_fields = ('customer__empresa__nome', 'asaas_subscription_id')


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('subscription', 'amount', 'due_date', 'status', 'asaas_payment_id')
    search_fields = ('subscription__customer__empresa__nome', 'asaas_payment_id')
    list_filter = ('status',)


@admin.register(PricingPlan)
class PricingPlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'amount', 'periodicity', 'active', 'updated_at')
    list_filter = ('periodicity', 'active')
    search_fields = ('name',)
    ordering = ('sort_order', '-updated_at')
