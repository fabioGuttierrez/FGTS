from django.db import models
from empresas.models import Empresa
from funcionarios.models import Funcionario

class Lancamento(models.Model):
	empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='lancamentos')
	funcionario = models.ForeignKey(Funcionario, on_delete=models.CASCADE, related_name='lancamentos')
	competencia = models.CharField(max_length=7)  # Ex: MM/YYYY
	base_fgts = models.DecimalField(max_digits=12, decimal_places=2)
	valor_fgts = models.DecimalField(max_digits=12, decimal_places=2)
	pago = models.BooleanField(default=False)
	data_pagto = models.DateField(null=True, blank=True)
	valor_pago = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
	# Adicione outros campos conforme necessário

	def __str__(self):
		return f"{self.empresa} - {self.funcionario} - {self.competencia}"
