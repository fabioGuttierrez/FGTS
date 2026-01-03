"""
Importador de dados legados do sistema VB6
Migra dados históricos de clientes antigos para novo sistema
"""

import csv
from decimal import Decimal
from datetime import datetime
from typing import List, Dict, Tuple
from django.db import transaction
from django.core.exceptions import ValidationError

from empresas.models import Empresa
from funcionarios.models import Funcionario
from lancamentos.models import Lancamento
from coefjam.models import CoefJam
from indices.models import IndiceFGTS


class LegacyDataImporter:
    """Importa dados históricos do sistema legado VB6"""

    def __init__(self):
        self.erros: List[str] = []
        self.avisos: List[str] = []
        self.linhas_processadas = 0
        self.registros_criados = 0
        self.registros_duplicados = 0

    def importar_empresas(self, arquivo_csv: str) -> Tuple[int, List[str]]:
        """
        Importa tabela de empresas do CSV legado

        Formato esperado:
        EmpresaID,CNPJ,RazaoSocial,Endereco,Numero,Bairro,Cidade,UF,CEP,Telefone,RAT,FPAS,CNAE,Simples

        Returns:
            (total_importados, lista_erros)
        """
        criados = 0
        
        try:
            with open(arquivo_csv, 'r', encoding='latin1') as f:
                reader = csv.DictReader(f)
                
                for linha_num, row in enumerate(reader, 2):
                    try:
                        cnpj = row.get('CNPJ', '').strip()
                        if not cnpj:
                            self.avisos.append(f"Linha {linha_num}: CNPJ vazio, pulando")
                            continue

                        # Verificar se já existe
                        if Empresa.objects.filter(cnpj=cnpj).exists():
                            self.registros_duplicados += 1
                            continue

                        empresa = Empresa(
                            codigo=row.get('EmpresaID', '').strip(),
                            cnpj=cnpj,
                            razao_social=row.get('RazaoSocial', '').strip(),
                            endereco=row.get('Endereco', '').strip(),
                            numero=row.get('Numero', '').strip(),
                            bairro=row.get('Bairro', '').strip(),
                            cidade=row.get('Cidade', '').strip(),
                            uf=row.get('UF', 'SP').strip()[:2],
                            cep=row.get('CEP', '').strip(),
                            telefone=row.get('Telefone', '').strip(),
                        )
                        
                        # Campos numéricos opcionais
                        try:
                            empresa.rat = int(row.get('RAT', 0) or 0)
                            empresa.fpas = int(row.get('FPAS', 0) or 0)
                        except (ValueError, TypeError):
                            pass
                        
                        empresa.cnae = row.get('CNAE', '').strip()[:8]
                        empresa.simples = row.get('Simples', 'N').strip()[0].upper()
                        
                        empresa.save()
                        criados += 1
                        self.linhas_processadas += 1

                    except Exception as e:
                        self.erros.append(f"Linha {linha_num}: {str(e)}")

        except FileNotFoundError:
            self.erros.append(f"Arquivo não encontrado: {arquivo_csv}")
        except Exception as e:
            self.erros.append(f"Erro ao importar empresas: {str(e)}")

        self.registros_criados += criados
        return criados, self.erros

    def importar_funcionarios(self, arquivo_csv: str, empresa_id: int = None) -> Tuple[int, List[str]]:
        """
        Importa funcionários do CSV legado

        Formato esperado:
        EmpresaID,FuncionarioID,Nome,PIS,DataAdmissao,DataNascimento,CBO,CarteiraProfissional,Serie

        Args:
            arquivo_csv: Caminho do arquivo CSV
            empresa_id: Se fornecido, importa apenas para esta empresa

        Returns:
            (total_importados, lista_erros)
        """
        criados = 0

        try:
            with open(arquivo_csv, 'r', encoding='latin1') as f:
                reader = csv.DictReader(f)

                for linha_num, row in enumerate(reader, 2):
                    try:
                        empresa_id_csv = int(row.get('EmpresaID', 0) or 0)
                        
                        if empresa_id and empresa_id_csv != empresa_id:
                            continue

                        # Buscar empresa
                        try:
                            empresa = Empresa.objects.get(codigo=str(empresa_id_csv))
                        except Empresa.DoesNotExist:
                            self.avisos.append(f"Linha {linha_num}: Empresa {empresa_id_csv} não encontrada")
                            continue

                        pis = row.get('PIS', '').strip()
                        if not pis:
                            self.avisos.append(f"Linha {linha_num}: PIS vazio")
                            continue

                        # Verificar duplicata
                        if Funcionario.objects.filter(empresa=empresa, pis=pis).exists():
                            self.registros_duplicados += 1
                            continue

                        # Parsear datas
                        data_adm = self._parse_data(row.get('DataAdmissao'))
                        data_nasc = self._parse_data(row.get('DataNascimento'))

                        funcionario = Funcionario(
                            empresa=empresa,
                            nome=row.get('Nome', '').strip(),
                            pis=pis,
                            data_admissao=data_adm,
                            data_nascimento=data_nasc,
                            cbo=row.get('CBO', '').strip(),
                            carteira_profissional=row.get('CarteiraProfissional', '').strip(),
                            serie_profissional=row.get('Serie', '1').strip(),
                        )
                        funcionario.save()
                        criados += 1
                        self.linhas_processadas += 1

                    except Exception as e:
                        self.erros.append(f"Linha {linha_num}: {str(e)}")

        except FileNotFoundError:
            self.erros.append(f"Arquivo não encontrado: {arquivo_csv}")
        except Exception as e:
            self.erros.append(f"Erro ao importar funcionários: {str(e)}")

        self.registros_criados += criados
        return criados, self.erros

    def importar_lancamentos(self, arquivo_csv: str) -> Tuple[int, List[str]]:
        """
        Importa lançamentos históricos (base FGTS)

        Formato esperado:
        EmpresaID,FuncionarioID,Competencia,BaseFGTS,DataPagamento,Pago

        Args:
            arquivo_csv: Caminho do arquivo CSV

        Returns:
            (total_importados, lista_erros)
        """
        criados = 0

        try:
            with open(arquivo_csv, 'r', encoding='latin1') as f:
                reader = csv.DictReader(f)

                for linha_num, row in enumerate(reader, 2):
                    try:
                        empresa_id = row.get('EmpresaID', '').strip()
                        func_id = row.get('FuncionarioID', '').strip()
                        competencia = row.get('Competencia', '').strip()

                        if not all([empresa_id, func_id, competencia]):
                            self.avisos.append(f"Linha {linha_num}: Dados incompletos")
                            continue

                        # Buscar empresa e funcionário
                        try:
                            empresa = Empresa.objects.get(codigo=empresa_id)
                            funcionario = Funcionario.objects.get(empresa=empresa, id=int(func_id))
                        except (Empresa.DoesNotExist, Funcionario.DoesNotExist, ValueError):
                            self.avisos.append(f"Linha {linha_num}: Empresa ou funcionário não encontrado")
                            continue

                        # Verificar duplicata
                        if Lancamento.objects.filter(
                            empresa=empresa,
                            funcionario=funcionario,
                            competencia=competencia
                        ).exists():
                            self.registros_duplicados += 1
                            continue

                        # Parsear valores
                        try:
                            base_fgts = Decimal(row.get('BaseFGTS', 0) or 0)
                        except:
                            base_fgts = Decimal('0')

                        data_pag = self._parse_data(row.get('DataPagamento'))
                        pago = row.get('Pago', 'N').upper() == 'S'

                        lancamento = Lancamento(
                            empresa=empresa,
                            funcionario=funcionario,
                            competencia=competencia,
                            base_fgts=base_fgts,
                            valor_fgts=base_fgts * Decimal('0.08'),  # 8% padrão
                            data_pagamento=data_pag,
                            pago=pago,
                        )
                        lancamento.save()
                        criados += 1
                        self.linhas_processadas += 1

                    except Exception as e:
                        self.erros.append(f"Linha {linha_num}: {str(e)}")

        except FileNotFoundError:
            self.erros.append(f"Arquivo não encontrado: {arquivo_csv}")
        except Exception as e:
            self.erros.append(f"Erro ao importar lançamentos: {str(e)}")

        self.registros_criados += criados
        return criados, self.erros

    @staticmethod
    def _parse_data(data_str: str) -> datetime.date:
        """Tenta parsear data em vários formatos comuns"""
        if not data_str or not data_str.strip():
            return None

        data_str = data_str.strip()
        formatos = [
            '%d/%m/%Y', '%Y/%m/%d', '%d-%m-%Y', '%Y-%m-%d',
            '%d%m%Y', '%Y%m%d',
        ]

        for fmt in formatos:
            try:
                return datetime.strptime(data_str, fmt).date()
            except ValueError:
                continue

        return None

    def relatorio(self) -> Dict:
        """Retorna relatório da importação"""
        return {
            'linhas_processadas': self.linhas_processadas,
            'registros_criados': self.registros_criados,
            'registros_duplicados': self.registros_duplicados,
            'erros': self.erros,
            'avisos': self.avisos,
            'total_problemas': len(self.erros) + len(self.avisos),
        }
