from django.contrib import admin
from .models import BillingCustomer, Subscription, Payment, PricingPlan


@admin.register(BillingCustomer)
class BillingCustomerAdmin(admin.ModelAdmin):
    list_display = ('empresa', 'status', 'asaas_customer_id', 'email_cobranca', 'created_at')
    search_fields = ('empresa__nome', 'asaas_customer_id')


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
