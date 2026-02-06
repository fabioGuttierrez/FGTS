from datetime import datetime
from io import BytesIO
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from django.utils.timezone import make_aware
from django.core.exceptions import ValidationError
from django.db import transaction
from fgtsweb.utils.validators import digits_only, normalize_upper_ascii, validate_cpf
from .models import Funcionario
from empresas.models import Empresa
from empresas.models_grupo import FuncionarioVinculo
from billing.models import BillingCustomer
from fgtsweb.mixins import is_empresa_allowed


class FuncionarioImportService:
    """Serviço para gerenciar importação e exportação de funcionários em XLSX"""
    
    REQUIRED_COLUMNS = [
        'NOME', 'CPF', 'DATA_ADMISSAO', 'EMPRESA'
    ]
    
    OPTIONAL_COLUMNS = [
        'PIS', 'CBO', 'CARTEIRA_PROFISSIONAL', 
        'SERIE_CARTEIRA', 'DATA_NASCIMENTO', 'DATA_DEMISSAO', 'OBSERVACAO', 'SALARIO'
    ]

    @staticmethod
    def _resolve_empresa_from_identifier(value):
        if value is None:
            return None

        raw = str(value).strip()
        if not raw:
            return None

        if raw.endswith('.0') and raw.replace('.', '', 1).isdigit():
            raw = str(int(float(raw)))

        qs = Empresa.objects.filter(codigo_folha__iexact=raw)
        if qs.count() > 1:
            raise ValueError(f"Codigo Folha '{raw}' duplicado. Contate o administrador.")
        if qs.exists():
            return qs.first()

        if raw.isdigit():
            try:
                return Empresa.objects.get(codigo=int(raw))
            except Empresa.DoesNotExist:
                return None

        return None
    
    @staticmethod
    def generate_template_xlsx():
        """Gera um arquivo XLSX com o modelo para importação de funcionários"""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Funcionários"
        
        # Definir estilos
        header_fill = PatternFill(start_color="667eea", end_color="667eea", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF", size=11)
        example_fill = PatternFill(start_color="E7E9FF", end_color="E7E9FF", fill_type="solid")
        border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )
        
        # Headers com colunas obrigatórias e opcionais
        all_columns = FuncionarioImportService.REQUIRED_COLUMNS + FuncionarioImportService.OPTIONAL_COLUMNS
        
        for col_idx, column_name in enumerate(all_columns, 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.value = column_name
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            cell.border = border
        
        # Adicionar linha de exemplo
        example_data = [
            "João da Silva",  # NOME
            "123.456.789-00",  # CPF
            "2023-01-15",  # DATA_ADMISSAO
            "EMP001",  # EMPRESA (codigo folha)
            "120.123.456-70",  # PIS
            "2110",  # CBO
            "AB123456",  # CARTEIRA_PROFISSIONAL
            "12",  # SERIE_CARTEIRA
            "1990-05-10",  # DATA_NASCIMENTO
            "",  # DATA_DEMISSAO
            "Informações adicionais",  # OBSERVACAO
            "3500.00",  # SALARIO
        ]
        
        for col_idx, value in enumerate(example_data, 1):
            cell = ws.cell(row=2, column=col_idx)
            cell.value = value
            cell.fill = example_fill
            cell.border = border
            header_name = all_columns[col_idx - 1]
            if header_name in ['DATA_ADMISSAO', 'DATA_NASCIMENTO', 'DATA_DEMISSAO']:
                cell.number_format = 'YYYY-MM-DD'
        
        # Adicionar informações
        info_row = 4
        ws.merge_cells(f'A{info_row}:D{info_row}')
        info_cell = ws[f'A{info_row}']
        info_cell.value = "⚠️ INSTRUÇÕES DE PREENCHIMENTO"
        info_cell.font = Font(bold=True, size=10, color="764ba2")
        
        instructions = [
            "• Campos obrigatórios: NOME, CPF, DATA_ADMISSAO, EMPRESA",
            "• Formato de datas: YYYY-MM-DD (ex: 2023-01-15)",
            "• CPF deve estar no formato XXX.XXX.XXX-XX",
            "• EMPRESA: use o CODIGO FOLHA da empresa (pode conter letras)",
            "• Para ver o codigo folha, acesse a lista de empresas no sistema",
            "• PIS é opcional e pode conter CPF (conforme regra atual)",
            "• DATA_DEMISSAO deixar em branco se o funcionário está ativo",
            "• SALARIO: se preenchido, cria automaticamente o primeiro lançamento de FGTS",
            "• SALARIO formato: número com ponto (ex: 3500.00)",
            "• Não altere os nomes das colunas ou a ordem delas",
            "• Apague a linha de exemplo antes de importar seus dados",
        ]
        
        for idx, instruction in enumerate(instructions, 1):
            instr_row = info_row + idx
            ws.merge_cells(f'A{instr_row}:D{instr_row}')
            instr_cell = ws[f'A{instr_row}']
            instr_cell.value = instruction
            instr_cell.font = Font(size=9)
            instr_cell.alignment = Alignment(wrap_text=True, vertical='top')
        
        # Ajustar largura das colunas
        ws.column_dimensions['A'].width = 20
        ws.column_dimensions['B'].width = 18
        ws.column_dimensions['C'].width = 15
        ws.column_dimensions['D'].width = 12
        ws.column_dimensions['E'].width = 15
        ws.column_dimensions['F'].width = 18
        ws.column_dimensions['G'].width = 10
        ws.column_dimensions['H'].width = 18
        ws.column_dimensions['I'].width = 15
        ws.column_dimensions['J'].width = 15
        ws.column_dimensions['K'].width = 15
        ws.column_dimensions['L'].width = 30
        
        # Definir altura da linha de header
        ws.row_dimensions[1].height = 30
        
        return wb
    
    @staticmethod
    def parse_date(date_value):
        """Converte valor de data para objeto datetime"""
        if not date_value or date_value.strip() == "":
            return None
        
        if isinstance(date_value, datetime):
            return date_value.date()
        
        # Tentar diferentes formatos
        for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y']:
            try:
                return datetime.strptime(str(date_value).strip(), fmt).date()
            except ValueError:
                continue
        
        raise ValueError(f"Formato de data inválido: {date_value}. Use YYYY-MM-DD ou DD/MM/YYYY")
    
    @staticmethod
    def import_funcionarios_from_file(file, empresa_id=None, user=None):
        """
        Importa funcionários de um arquivo XLSX
        
        Args:
            file: arquivo XLSX
            empresa_id: ID da empresa (opcional, pode estar no arquivo)
            user: usuário que está realizando a importação
            
        Returns:
            dict com estatísticas da importação
        """
        try:
            wb = openpyxl.load_workbook(file)
            ws = wb.active
            
            # Obter headers
            headers = {}
            for col_idx, cell in enumerate(ws[1], 1):
                if cell.value:
                    headers[cell.value.upper()] = col_idx
            
            # Validar colunas obrigatórias
            missing_columns = [col for col in FuncionarioImportService.REQUIRED_COLUMNS if col not in headers]
            if missing_columns:
                raise ValueError(f"Colunas obrigatórias faltando: {', '.join(missing_columns)}")
            
            result = {
                'total': 0,
                'success': 0,
                'errors': [],
                'created_funcionarios': []
            }
            
            # Processar linhas
            for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=False), 2):
                try:
                    row_data = {}
                    
                    # Extrair dados
                    for header, col_idx in headers.items():
                        cell = row[col_idx - 1]
                        row_data[header] = cell.value
                    
                    # Validar dados obrigatórios
                    if not row_data.get('NOME', '').strip():
                        raise ValueError("Nome é obrigatório")
                    
                    if not row_data.get('CPF', '').strip():
                        raise ValueError("CPF é obrigatório")
                    
                    if not row_data.get('DATA_ADMISSAO'):
                        raise ValueError("Data de admissão é obrigatória")
                    
                    # Validar e obter empresa
                    empresa_identifier = row_data.get('EMPRESA') or empresa_id
                    if not empresa_identifier:
                        raise ValueError("Empresa é obrigatória")
                    
                    empresa = FuncionarioImportService._resolve_empresa_from_identifier(empresa_identifier)
                    if not empresa:
                        raise ValueError(f"Empresa '{empresa_identifier}' não encontrada")
                    
                    # VALIDAÇÃO 1: Verificar se usuário tem permissão para essa empresa
                    if user and not is_empresa_allowed(user, empresa.codigo):
                        raise ValueError(
                            "A empresa informada no arquivo não faz parte do seu grupo de empresas. "
                            "Verifique o código da empresa e tente novamente."
                        )
                    
                    # VALIDAÇÃO 2: Verificar se empresa tem billing ativo ou em trial
                    try:
                        billing_customer = empresa.billing_customer
                        if billing_customer.status not in ['active', 'trial']:
                            raise ValueError(
                                f"Empresa '{empresa.nome}' não possui assinatura ativa. "
                                f"Status atual: {billing_customer.get_status_display()}. "
                                f"Entre em contato com o administrador para regularizar."
                            )
                        
                        # ✅ EMPRESAS EM TRIAL TÊM LIMITE ILIMITADO!
                        if billing_customer.status == 'trial':
                            pass  # Pula validação de limite para empresas trial
                        # VALIDAÇÃO 3: Verificar limite de funcionários do plano (apenas para empresas active)
                        elif billing_customer.plan:
                            # Contar funcionários ativos da empresa
                            active_count = empresa.funcionarios.filter(data_demissao__isnull=True).count()
                            
                            # Verificar se pode adicionar mais um
                            if not billing_customer.plan.can_add_employee(active_count):
                                plan_name = billing_customer.plan.get_plan_type_display()
                                max_employees = billing_customer.plan.max_employees
                                raise ValueError(
                                    f"Plano '{plan_name}' da empresa '{empresa.nome}' permite no máximo "
                                    f"{max_employees} colaboradores ativos. "
                                    f"Já existem {active_count} cadastrados. "
                                    f"Faça upgrade do plano para adicionar mais."
                                )
                        else:
                            raise ValueError(
                                f"Empresa '{empresa.nome}' não possui plano configurado. "
                                f"Entre em contato com o administrador."
                            )
                    except Empresa.billing_customer.RelatedObjectDoesNotExist:
                        raise ValueError(
                            f"Empresa '{empresa.nome}' não possui configuração de billing. "
                            f"Entre em contato com o administrador."
                        )
                    
                    # Preparar dados do funcionário
                    funcionario_data = {
                        'nome': normalize_upper_ascii(row_data['NOME'], allow_digits=False),
                        'cpf': validate_cpf(row_data['CPF']),
                    }

                    # Campos opcionais com validação/normalização
                    if row_data.get('PIS'):
                        # Regra atual permite CPF no lugar do PIS; não validamos DV.
                        pis = digits_only(row_data['PIS'])
                        if len(pis) > 15:
                            raise ValueError('PIS muito longo. Informe no máximo 15 dígitos.')
                        funcionario_data['pis'] = pis

                    if row_data.get('CBO'):
                        funcionario_data['cbo'] = normalize_upper_ascii(row_data['CBO'], allow_digits=True)

                    if row_data.get('CARTEIRA_PROFISSIONAL'):
                        funcionario_data['carteira_profissional'] = normalize_upper_ascii(row_data['CARTEIRA_PROFISSIONAL'], allow_digits=True)

                    if row_data.get('SERIE_CARTEIRA'):
                        funcionario_data['serie_carteira'] = normalize_upper_ascii(row_data['SERIE_CARTEIRA'], allow_digits=True)

                    if row_data.get('DATA_NASCIMENTO'):
                        funcionario_data['data_nascimento'] = FuncionarioImportService.parse_date(row_data['DATA_NASCIMENTO'])

                    if row_data.get('OBSERVACAO'):
                        funcionario_data['observacao'] = normalize_upper_ascii(row_data['OBSERVACAO'], allow_digits=True)
                    
                    # Criar funcionário e vínculo de forma consistente
                    with transaction.atomic():
                        funcionario = Funcionario(**funcionario_data)
                        funcionario.save()

                        # Criar vínculo (empresa e datas vivem no vínculo, não no funcionário)
                        data_admissao = FuncionarioImportService.parse_date(row_data['DATA_ADMISSAO'])
                        data_demissao = None
                        if row_data.get('DATA_DEMISSAO'):
                            data_demissao = FuncionarioImportService.parse_date(row_data['DATA_DEMISSAO'])

                        FuncionarioVinculo.objects.create(
                            funcionario=funcionario,
                            empresa=empresa,
                            data_admissao=data_admissao,
                            data_demissao=data_demissao,
                            salario=str(row_data.get('SALARIO')).strip() if row_data.get('SALARIO') else None,
                        )

                        # Validar após vínculo existir
                        funcionario.full_clean()
                    
                    # Criar primeiro lançamento automaticamente se salário foi informado
                    salario_str = row_data.get('SALARIO')
                    if salario_str:
                        try:
                            from decimal import Decimal
                            from lancamentos.models import Lancamento
                            
                            salario = Decimal(str(salario_str).strip())
                            if salario > 0:
                                competencia = data_admissao.strftime('%m/%Y')
                                
                                # Verificar se já existe lançamento
                                existe = Lancamento.objects.filter(
                                    empresa=empresa,
                                    funcionario=funcionario,
                                    competencia=competencia,
                                    parcela_13__isnull=True
                                ).exists()
                                
                                if not existe:
                                    valor_fgts = salario * Decimal('0.08')
                                    Lancamento.objects.create(
                                        empresa=empresa,
                                        funcionario=funcionario,
                                        competencia=competencia,
                                        base_fgts=salario,
                                        valor_fgts=valor_fgts,
                                        pago=False
                                    )
                        except Exception as e:
                            # Log do erro mas não interrompe a importação
                            error_msg = f"Linha {row_idx}: Funcionário criado, mas erro ao criar lançamento: {str(e)}"
                            result['errors'].append(error_msg)
                    
                    result['success'] += 1
                    result['created_funcionarios'].append(funcionario.id)
                    
                except Exception as e:
                    error_msg = f"Linha {row_idx}: {str(e)}"
                    result['errors'].append(error_msg)
                
                result['total'] += 1
            
            return result
            
        except Exception as e:
            raise Exception(f"Erro ao processar arquivo: {str(e)}")
