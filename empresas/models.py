
from django.db import models

class Empresa(models.Model):
	OPTANTE_SIMPLES_CHOICES = [
		(1, 'Não Optante'),
		(2, 'Optante'),
	]
	
	codigo = models.AutoField(primary_key=True)
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

	def __str__(self):
		return self.nome
	
	class Meta:
		verbose_name = 'Empresa'
		verbose_name_plural = 'Empresas'
