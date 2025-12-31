from django.db import models
from django.contrib.auth.models import AbstractUser
from empresas.models import Empresa


class Usuario(AbstractUser):
	manutencao = models.BooleanField(default=False)
	# Empresa principal (escopo padrão do usuário)
	empresa = models.ForeignKey(
		Empresa,
		on_delete=models.PROTECT,
		null=True,
		blank=True,
		related_name='usuarios',
		verbose_name='Empresa'
	)
	# Permite atuar em múltiplas empresas (modo gestor multiempresas)
	empresas_permitidas = models.ManyToManyField(
		Empresa,
		blank=True,
		related_name='usuarios_permitidos',
		verbose_name='Empresas permitidas'
	)
	# Flag para indicar que pode operar várias empresas sem trocar login
	is_multi_empresa = models.BooleanField(default=False, verbose_name='Gestor multiempresas')

	def __str__(self):
		return self.username
