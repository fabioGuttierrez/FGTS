from django.urls import path
from . import views

urlpatterns = [
    path('', views.FuncionarioListView.as_view(), name='funcionario-list'),
    path('novo/', views.FuncionarioCreateView.as_view(), name='funcionario-create'),
    path('<int:pk>/editar/', views.FuncionarioUpdateView.as_view(), name='funcionario-update'),
    path('<int:pk>/excluir/', views.FuncionarioDeleteView.as_view(), name='funcionario-delete'),
]
