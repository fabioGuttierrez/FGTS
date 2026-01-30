from django.contrib import admin
from .admin_feature import * 
from .admin_grupo import *
from .models import Empresa


@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
	list_display = ('nome', 'cnpj', 'cidade', 'uf', 'grupo', 'is_matriz_flag')
	search_fields = ('nome', 'cnpj')
	list_filter = ('grupo',)

	@admin.display(description='Matriz?')
	def is_matriz_flag(self, obj):
		return obj.is_matriz
