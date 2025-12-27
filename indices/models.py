from django.db import models

class Indice(models.Model):
	competencia = models.CharField(max_length=7)  # Ex: MM/YYYY
	data_indice = models.DateField()
	valor = models.DecimalField(max_digits=12, decimal_places=8)

	def __str__(self):
		return f"{self.competencia} - {self.data_indice}"


class SupabaseIndice(models.Model):
	"""Modelo de leitura para a tabela existente no Supabase: indices_fgts.
	managed=False para não criar/migrar essa tabela via Django.
	Colunas reais: id (uuid), competencia (date), tabela (int), data_base (date), indice (decimal), created_at.
	"""
	competencia = models.DateField()
	tabela = models.IntegerField()
	data_base = models.DateField()
	indice = models.DecimalField(max_digits=12, decimal_places=9)
	created_at = models.DateTimeField()

	class Meta:
		managed = False
		db_table = 'indices_fgts'

	def __str__(self):
		return f"{self.competencia} - {self.data_base}"
