from django.db import models
from django.conf import settings

class GrupoEmpresa(models.Model):
    nome = models.CharField(max_length=255, unique=True)
    cnpj_base = models.CharField(max_length=20, blank=True, null=True)
    data_criacao = models.DateField(auto_now_add=True)
    observacoes = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.nome

class FuncionarioVinculo(models.Model):
    MOTIVO_SAIDA_CHOICES = [
        ("demissao", "Demissão"),
        ("transferencia", "Transferência para outra empresa do grupo"),
        ("outro", "Outro")
    ]
    funcionario = models.ForeignKey('funcionarios.Funcionario', on_delete=models.CASCADE, related_name='vinculos')
    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE)
    data_admissao = models.DateField()
    data_demissao = models.DateField(blank=True, null=True)
    motivo_saida = models.CharField(max_length=20, choices=MOTIVO_SAIDA_CHOICES, blank=True, null=True)
    observacoes = models.TextField(blank=True, null=True)
    cargo = models.CharField(max_length=100, blank=True, null=True)
    salario = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    data_transferencia = models.DateField(blank=True, null=True)

    def is_ativo_em_competencia(self, competencia):
        """
        Retorna True se o vínculo estava ativo na competência informada.
        Aceita: 'MM/YYYY', 'YYYY-MM', 'YYYY/MM' ou datetime.date
        """
        import datetime
        competencia_date = None
        if isinstance(competencia, str):
            try:
                if '/' in competencia:
                    parts = competencia.split('/')
                    if len(parts) == 2:
                        # MM/YYYY
                        if len(parts[1]) == 4:
                            mes, ano = int(parts[0]), int(parts[1])
                            competencia_date = datetime.date(ano, mes, 1)
                        # YYYY/MM
                        elif len(parts[0]) == 4:
                            ano, mes = int(parts[0]), int(parts[1])
                            competencia_date = datetime.date(ano, mes, 1)
                elif '-' in competencia:
                    parts = competencia.split('-')
                    if len(parts) == 2 and len(parts[0]) == 4:
                        # YYYY-MM
                        ano, mes = int(parts[0]), int(parts[1])
                        competencia_date = datetime.date(ano, mes, 1)
            except Exception:
                return False
        elif isinstance(competencia, datetime.date):
            competencia_date = competencia.replace(day=1)
        else:
            return False

        if competencia_date is None:
            return False

        # Considerar ativo durante todo o mês de admissão e demissão (ignorar o dia)
        admissao_mes_ano = (self.data_admissao.year, self.data_admissao.month)
        competencia_mes_ano = (competencia_date.year, competencia_date.month)
        if self.data_demissao:
            demissao_mes_ano = (self.data_demissao.year, self.data_demissao.month)
            admitido = competencia_mes_ano >= admissao_mes_ano
            nao_demitido = competencia_mes_ano <= demissao_mes_ano
        else:
            admitido = competencia_mes_ano >= admissao_mes_ano
            nao_demitido = True
        return admitido and nao_demitido
    funcionario = models.ForeignKey('funcionarios.Funcionario', on_delete=models.CASCADE, related_name='vinculos')
    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE)
    data_admissao = models.DateField()
    data_demissao = models.DateField(blank=True, null=True)
    motivo_saida = models.CharField(max_length=20, choices=MOTIVO_SAIDA_CHOICES, blank=True, null=True)
    observacoes = models.TextField(blank=True, null=True)
    cargo = models.CharField(max_length=100, blank=True, null=True)
    salario = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    data_transferencia = models.DateField(blank=True, null=True)

    def __str__(self):
        return f"{self.funcionario.nome} - {self.empresa.nome} ({self.data_admissao} a {self.data_demissao or 'atual'})"

class TransferenciaFuncionario(models.Model):
    funcionario = models.ForeignKey('funcionarios.Funcionario', on_delete=models.CASCADE)
    empresa_origem = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='transferencias_saida')
    empresa_destino = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='transferencias_entrada')
    data_transferencia = models.DateField(auto_now_add=True)
    usuario_responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    observacoes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.funcionario.nome}: {self.empresa_origem.nome} → {self.empresa_destino.nome} em {self.data_transferencia}"
