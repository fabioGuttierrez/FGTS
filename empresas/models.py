from django.db import models
from .models_feature import * 
from .models_grupo import *

class Empresa(models.Model):
	OPTANTE_SIMPLES_CHOICES = [
		(1, 'Não Optante'),
		(2, 'Optante'),
	]
	
	# OBS: o banco atual usa PK na coluna "id". Mantemos o atributo "codigo"
	# por compatibilidade no código, mapeando para a coluna correta.
	codigo = models.AutoField(primary_key=True, db_column='id')
	grupo = models.ForeignKey('GrupoEmpresa', null=True, blank=True, on_delete=models.SET_NULL, related_name='empresas', verbose_name='Grupo Econômico')
	nome = models.CharField(max_length=255, verbose_name='Nome')
	cnpj = models.CharField(max_length=20, unique=True, verbose_name='CNPJ')
	endereco = models.CharField(max_length=255, blank=True, verbose_name='Endereço')
	numero = models.CharField(max_length=10, blank=True, verbose_name='Número')
	bairro = models.CharField(max_length=100, blank=True, verbose_name='Bairro')
	cep = models.CharField(max_length=10, blank=True, verbose_name='CEP')
	cidade = models.CharField(max_length=100, blank=True, verbose_name='Cidade')
	uf = models.CharField(max_length=2, blank=True, verbose_name='UF')
	nome_contato = models.CharField(max_length=255, blank=True, verbose_name='Nome Contato')
	fone_contato = models.CharField(max_length=20, blank=True, verbose_name='Fone de Contato')
	cnae = models.CharField(max_length=10, blank=True, verbose_name='CNAE')
	percentual_rat = models.DecimalField(max_digits=5, decimal_places=2, default=1, verbose_name='% RAT')
	optante_simples = models.IntegerField(choices=OPTANTE_SIMPLES_CHOICES, default=1, verbose_name='Optante Simples')
	fpas = models.CharField(max_length=10, blank=True, verbose_name='FPAS')
	outras_entidades = models.CharField(max_length=10, blank=True, verbose_name='Outras Entidades')
	email = models.EmailField(blank=True, verbose_name='e-Mail')
	paga_13_aniversario = models.BooleanField(
		default=False,
		verbose_name='Paga 1ª parcela do 13º no mês de aniversário?',
		help_text='Se marcado, a 1ª parcela do 13º será paga no mês de aniversário do colaborador (ao invés de novembro). A 2ª parcela continua sendo paga em dezembro.'
	)

	def __str__(self):
		return self.nome
	
	class Meta:
		verbose_name = 'Empresa'
		verbose_name_plural = 'Empresas'
