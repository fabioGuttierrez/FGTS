from django.db import models
from django.contrib.auth.models import AbstractUser

class Usuario(AbstractUser):
	manutencao = models.BooleanField(default=False)
	# Adicione outros campos de permissão conforme necessário

	def __str__(self):
		return self.username
