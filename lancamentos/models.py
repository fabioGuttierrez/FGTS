from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from decimal import Decimal
from empresas.models import Empresa
from funcionarios.models import Funcionario
from datetime import datetime
from dateutil.relativedelta import relativedelta

class Lancamento(models.Model):
	PARCELA_CHOICES = [
		(None, 'Competência Normal (01-12)'),
		(1, '13º Salário - 1ª Parcela'),
		(2, '13º Salário - 2ª Parcela'),
	]
	
	empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='lancamentos')
	funcionario = models.ForeignKey(Funcionario, on_delete=models.CASCADE, related_name='lancamentos')
	vinculo = models.ForeignKey(
		'empresas.FuncionarioVinculo',
		on_delete=models.PROTECT,
		null=True,
		blank=True,
		related_name='lancamentos',
		help_text='Opcional. Identifica a "cadeira" (vínculo) do funcionário para esta competência.'
	)
	competencia = models.CharField(max_length=7)  # Ex: MM/YYYY ou 13/YYYY para 13º
	parcela_13 = models.PositiveSmallIntegerField(
		null=True, 
		blank=True, 
		choices=PARCELA_CHOICES,
		help_text="Se preenchido, indica que é uma das 2 parcelas do 13º salário"
	)
	base_fgts = models.DecimalField(max_digits=12, decimal_places=2)
	valor_fgts = models.DecimalField(max_digits=12, decimal_places=2)
	horas_extras = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, default=Decimal('0.00'), help_text="Valores variáveis como horas extras")
	adicionais = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, default=Decimal('0.00'), help_text="Adicionais salariais")
	desconto_inss = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, default=Decimal('0.00'), help_text="Desconto de INSS")
	desconto_ir = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, default=Decimal('0.00'), help_text="Desconto de IR")
	desconto_sindical = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, default=Decimal('0.00'), help_text="Contribuição sindical")
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
		# Garantir consistência do vínculo (quando informado)
		if self.vinculo_id:
			if not self.empresa_id:
				self.empresa_id = self.vinculo.empresa_id
			if not self.funcionario_id:
				self.funcionario_id = self.vinculo.funcionario_id
			# Se usuário tentou salvar inconsistente, força coerência
			if self.empresa_id != self.vinculo.empresa_id:
				self.empresa_id = self.vinculo.empresa_id
			if self.funcionario_id != self.vinculo.funcionario_id:
				self.funcionario_id = self.vinculo.funcionario_id

		# Detectar se é uma edição e se a base_fgts mudou
		base_fgts_mudou = False
		if self.pk:  # Se já existe no banco (edição)
			try:
				lancamento_antigo = Lancamento.objects.get(pk=self.pk)
				if lancamento_antigo.base_fgts != self.base_fgts:
					base_fgts_mudou = True
			except Lancamento.DoesNotExist:
				pass

		# Recalcular valor_fgts sempre que a base mudar
		if self.base_fgts is not None:
			valor_calculado = self.base_fgts * Decimal('0.08')
			if base_fgts_mudou or self.valor_fgts is None or self.valor_fgts != valor_calculado:
				self.valor_fgts = valor_calculado
		
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

	def clean(self):
		super().clean()

		# Se vínculo foi informado, derive empresa/funcionário dele
		if self.vinculo_id:
			if self.empresa_id and self.empresa_id != self.vinculo.empresa_id:
				raise ValidationError({'vinculo': 'Vínculo não pertence à empresa selecionada.'})
			if self.funcionario_id and self.funcionario_id != self.vinculo.funcionario_id:
				raise ValidationError({'vinculo': 'Vínculo não pertence ao funcionário selecionado.'})
			self.empresa_id = self.vinculo.empresa_id
			self.funcionario_id = self.vinculo.funcionario_id

		if not self.competencia:
			return

		# Garantir que empresa e funcionário estejam definidos antes das validações
		if not self.empresa_id:
			raise ValidationError({'empresa': 'Empresa é obrigatória.'})
		if not self.funcionario_id:
			raise ValidationError({'funcionario': 'Funcionário é obrigatório.'})

		try:
			mes, ano = map(int, self.competencia.split('/'))
		except Exception:
			raise ValidationError({'competencia': 'Competência deve estar no formato MM/YYYY.'})

		if mes < 1 or mes > 12:
			raise ValidationError({'competencia': 'Mês deve estar entre 01 e 12.'})

		# Limite de histórico por plano/empresa
		try:
			billing_customer = self.empresa.billing_customer
			max_history_months = billing_customer.get_effective_max_history_months()
			if max_history_months is not None and max_history_months > 0:
				competencia_date = datetime(ano, mes, 1).date()
				today = datetime.today().date()
				current_month = datetime(today.year, today.month, 1).date()
				min_date = current_month - relativedelta(months=max_history_months - 1)
				if competencia_date < min_date:
					raise ValidationError({
						'competencia': (
							f"Competência fora do limite do seu plano: "
							f"máximo de {max_history_months} meses de histórico."
						)
					})
		except Exception:
			pass

		# Validação das parcelas do 13º
		if self.parcela_13:
			if self.parcela_13 == 1:
				mes_esperado = 11
				if getattr(self.empresa, 'paga_13_aniversario', False):
					aniversario = getattr(self.funcionario, 'data_nascimento', None)
					if aniversario:
						mes_esperado = aniversario.month
				if mes != mes_esperado:
					raise ValidationError({'competencia': f"1ª parcela do 13º deve ser em {mes_esperado:02d}/{ano}."})
			elif self.parcela_13 == 2:
				if mes != 12:
					raise ValidationError({'competencia': '2ª parcela do 13º deve ser em 12.'})
		else:
			# Competência normal já validada pelo intervalo do mês acima
			pass
	
	def atualizar_lancamentos_posteriores(self):
		"""
		Atualiza todos os lançamentos posteriores do mesmo funcionário com a nova base_fgts.
		Isso implementa a cascata de reajuste salarial.
		"""
		try:
			# Converter competência atual para data
			mes, ano = map(int, self.competencia.split('/'))
			data_atual = datetime(ano, mes, 1)
			
			# Buscar todos os lançamentos posteriores do mesmo funcionário (ou do mesmo vínculo, quando aplicável)
			filtro = {'funcionario': self.funcionario}
			if self.vinculo_id:
				filtro = {'vinculo_id': self.vinculo_id}

			lancamentos_posteriores = Lancamento.objects.filter(**filtro).order_by('competencia')
			
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
	def obter_base_fgts_anterior(funcionario, competencia_str, vinculo=None):
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
			
			filtro = {'funcionario': funcionario, 'competencia': competencia_anterior}
			if vinculo is not None:
				filtro = {'vinculo': vinculo, 'competencia': competencia_anterior}

			lancamento_anterior = Lancamento.objects.filter(**filtro).first()
			
			if lancamento_anterior:
				return lancamento_anterior.base_fgts
			else:
				# Se não encontrou, tenta o mês anterior ao anterior
				if data_anterior.month > 1 or data_anterior.year > 2020:
					return Lancamento.obter_base_fgts_anterior(funcionario, competencia_anterior, vinculo=vinculo)
		except:
			pass
		
		return None

	class Meta:
		verbose_name = 'Lançamento'
		verbose_name_plural = 'Lançamentos'
		# Permite mais de um lançamento no mesmo mês para o mesmo CPF, desde que seja em vínculos diferentes.
		# Mantém compatibilidade com registros legados (vinculo nulo).
		unique_together = ('empresa', 'funcionario', 'competencia', 'parcela_13', 'vinculo')
