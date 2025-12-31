from django.db import models
from django.utils import timezone
from decimal import Decimal
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
	pago = models.BooleanField(default=False, help_text="FGTS foi pago?")
	data_pagto = models.DateField(null=True, blank=True, verbose_name="Data de Pagamento", help_text="Data em que o FGTS foi efetivamente pago")
	valor_pago = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Valor Pago")
	pago_em = models.DateTimeField(null=True, blank=True, verbose_name="Marcado como pago em", help_text="Data/hora em que foi registrado como pago no sistema")
	criado_em = models.DateTimeField(auto_now_add=True)
	atualizado_em = models.DateTimeField(auto_now=True)

	def __str__(self):
		return f"{self.empresa} - {self.funcionario} - {self.competencia}"
	
	def save(self, *args, **kwargs):
		"""
		Sobrescreve o save para:
		1. Registrar automaticamente quando marcar como pago
		2. Atualizar lançamentos posteriores quando houver mudança na base_fgts (cascata de reajuste)
		"""
		# Detectar se é uma edição e se a base_fgts mudou
		base_fgts_mudou = False
		if self.pk:  # Se já existe no banco (edição)
			try:
				lancamento_antigo = Lancamento.objects.get(pk=self.pk)
				if lancamento_antigo.base_fgts != self.base_fgts:
					base_fgts_mudou = True
			except Lancamento.DoesNotExist:
				pass
		
		# Controle de pagamento: registrar timestamp
		if self.pago and not self.pago_em:
			self.pago_em = timezone.now()
		elif not self.pago:
			self.pago_em = None
		
		# Salvar o lançamento atual
		super().save(*args, **kwargs)
		
		# Se houve mudança na base_fgts, atualizar todos os lançamentos posteriores
		if base_fgts_mudou:
			self.atualizar_lancamentos_posteriores()
	
	def atualizar_lancamentos_posteriores(self):
		"""
		Atualiza todos os lançamentos posteriores do mesmo funcionário com a nova base_fgts.
		Isso implementa a cascata de reajuste salarial.
		"""
		try:
			# Converter competência atual para data
			mes, ano = map(int, self.competencia.split('/'))
			data_atual = datetime(ano, mes, 1)
			
			# Buscar todos os lançamentos posteriores do mesmo funcionário
			lancamentos_posteriores = Lancamento.objects.filter(
				funcionario=self.funcionario
			).order_by('competencia')
			
			# Filtrar apenas os meses posteriores ao atual
			for lancamento in lancamentos_posteriores:
				try:
					mes_l, ano_l = map(int, lancamento.competencia.split('/'))
					data_lancamento = datetime(ano_l, mes_l, 1)
					
					# Se for posterior, atualizar
					if data_lancamento > data_atual:
						lancamento.base_fgts = self.base_fgts
						lancamento.valor_fgts = self.base_fgts * Decimal('0.08')  # Recalcular 8%
						# Usar update direto para evitar recursão infinita
						Lancamento.objects.filter(pk=lancamento.pk).update(
							base_fgts=lancamento.base_fgts,
							valor_fgts=lancamento.valor_fgts
						)
				except:
					continue
					
		except Exception as e:
			# Não interromper o fluxo em caso de erro na cascata
			pass
	
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
