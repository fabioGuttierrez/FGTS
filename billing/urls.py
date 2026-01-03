from django.urls import path
from .views import CheckoutPlanoView, checkout_empresa, asaas_webhook, FeedbackCreateView, FeedbackListView

urlpatterns = [
    # Checkout público - selecionar plano
    path('checkout/', CheckoutPlanoView.as_view(), name='checkout-plano'),
    path('checkout/<str:plan_type>/', CheckoutPlanoView.as_view(), name='checkout-plano-tipo'),
    
    # Checkout para empresa (requer login)
    path('checkout-empresa/<int:empresa_id>/', checkout_empresa, name='billing-checkout-empresa'),
    
    # Feedback
    path('feedback/', FeedbackCreateView.as_view(), name='feedback-criar'),
    path('feedback/admin/', FeedbackListView.as_view(), name='feedback-admin'),
    
    # Webhook do Asaas
    path('webhook/', asaas_webhook, name='billing-webhook'),
]
