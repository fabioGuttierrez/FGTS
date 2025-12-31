from django.urls import path
from .views import UsuarioRegisterView

urlpatterns = [
    path('registrar/', UsuarioRegisterView.as_view(), name='register'),
]
