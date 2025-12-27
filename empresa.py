from django.db import models

class Empresa(models.Model):
    nome = models.CharField(max_length=255)
    cnpj = models.CharField(max_length=20, unique=True)
    endereco = models.CharField(max_length=255, blank=True)
    
    def __str__(self):
        return self.nome
