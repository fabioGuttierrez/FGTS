from django.db import models
from empresas.models import Empresa
from funcionarios.models import Funcionario
from datetime import datetime
from dateutil.relativedelta import relativedelta

class Lancamento(models.Model):
	empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='lancamentos')
	funcionario = models.ForeignKey(Funcionario, on_delete=models.CASCADE, related_name='lancamentos')
	competencia = models.CharField(max_length=7)  # Ex: MM/YYYY
	base_fgts = models.DecimalField(max_digits=12, decimal_places=2)
	valor_fgts = models.DecimalField(max_digits=12, decimal_places=2)
	pago = models.BooleanField(default=False)
	data_pagto = models.DateField(null=True, blank=True)
	valor_pago = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
	criado_em = models.DateTimeField(auto_now_add=True)
	atualizado_em = models.DateTimeField(auto_now=True)

	def __str__(self):
		return f"{self.empresa} - {self.funcionario} - {self.competencia}"
	
	@staticmethod
	def obter_base_fgts_anterior(funcionario, competencia_str):
		"""
		Obtém a base FGTS do mês anterior.
		Se não encontrar, retorna None e o sistema usa o mês anterior recursivamente.
		Exemplo: competencia_str = "01/2025" retorna a base de 12/2024
		"""
		try:
			mes, ano = map(int, competencia_str.split('/'))
			data_atual = datetime(ano, mes, 1)
			data_anterior = data_atual - relativedelta(months=1)
			competencia_anterior = data_anterior.strftime('%m/%Y')
			
			lancamento_anterior = Lancamento.objects.filter(
				funcionario=funcionario,
				competencia=competencia_anterior
			).first()
			
			if lancamento_anterior:
				return lancamento_anterior.base_fgts
			else:
				# Se não encontrou, tenta o mês anterior ao anterior
				if data_anterior.month > 1 or data_anterior.year > 2020:
					return Lancamento.obter_base_fgts_anterior(funcionario, competencia_anterior)
		except:
			pass
		
		return None

	class Meta:
		verbose_name = 'Lançamento'
		verbose_name_plural = 'Lançamentos'
		# Permite apenas um lançamento por funcionário por competência
		unique_together = ('funcionario', 'competencia')
