from django import forms
from django.core.exceptions import ValidationError
from empresas.models import Empresa
from funcionarios.models import Funcionario
from fgtsweb.mixins import get_allowed_empresa_ids
from .models import Lancamento


class LancamentoForm(forms.ModelForm):
    """Formulário para cadastro/edição de lançamentos mensais (base FGTS)"""
    
    class Meta:
        model = Lancamento
        fields = ['empresa', 'funcionario', 'competencia', 'parcela_13', 'base_fgts', 'pago', 'data_pagto', 'valor_pago']
        widgets = {
            'empresa': forms.Select(attrs={'autocomplete': 'off', 'class': 'form-select'}),
            'funcionario': forms.Select(attrs={'autocomplete': 'off', 'class': 'form-select'}),
            'competencia': forms.TextInput(attrs={
                'placeholder': 'MM/YYYY (ex: 01/2025)',
                'autocomplete': 'off',
                'class': 'form-control'
            }),
            'parcela_13': forms.Select(attrs={'autocomplete': 'off', 'class': 'form-select'}),
            'base_fgts': forms.NumberInput(attrs={
                'placeholder': 'Valor base para cálculo do FGTS',
                'step': '0.01',
                'class': 'form-control'
            }),
            'pago': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'data_pagto': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }),
            'valor_pago': forms.NumberInput(attrs={
                'placeholder': 'Valor efetivamente pago',
                'step': '0.01',
                'class': 'form-control'
            }),
        }
        labels = {
            'empresa': 'Empresa *',
            'funcionario': 'Funcionário *',
            'competencia': 'Competência (MM/YYYY) *',
            'parcela_13': 'Parcela do 13º Salário',
            'base_fgts': 'Base FGTS (Salário)',
            'pago': 'FGTS Pago?',
            'data_pagto': 'Data do Pagamento',
            'valor_pago': 'Valor Pago',
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        allowed_ids = None

        # Filtrar empresas permitidas
        if user is not None:
            allowed_ids = get_allowed_empresa_ids(user)
            if allowed_ids is not None:
                self.fields['empresa'].queryset = Empresa.objects.filter(codigo__in=allowed_ids)

        # Determinar empresa pré-selecionada (POST, initial ou instance)
        empresa_id = None
        data_dict = kwargs.get('data') or {}
        initial_dict = kwargs.get('initial') or {}

        if data_dict.get('empresa'):
            try:
                empresa_id = int(data_dict.get('empresa'))
            except (ValueError, TypeError):
                empresa_id = None
        elif initial_dict.get('empresa'):
            try:
                empresa_id = int(initial_dict.get('empresa'))
            except (ValueError, TypeError):
                empresa_id = None
        elif self.instance and getattr(self.instance, 'empresa_id', None):
            empresa_id = self.instance.empresa_id

        # Filtrar funcionários conforme empresa selecionada ou escopo permitido
        if empresa_id:
            self.fields['funcionario'].queryset = Funcionario.objects.filter(vinculos__empresa_id=empresa_id).distinct()
        elif allowed_ids is not None:
            self.fields['funcionario'].queryset = Funcionario.objects.filter(vinculos__empresa__codigo__in=allowed_ids).distinct()
        else:
            self.fields['funcionario'].queryset = Funcionario.objects.all()
    
    def save(self, commit=True):
        """Sobrescrever save para calcular valor_fgts automaticamente"""
        lancamento = super().save(commit=False)
        # ⚡ Calcular valor_fgts automaticamente (8% da base_fgts)
        base_fgts = lancamento.base_fgts
        if base_fgts and (lancamento.valor_fgts is None or lancamento.valor_fgts == 0):
            from decimal import Decimal
            lancamento.valor_fgts = base_fgts * Decimal('0.08')
        if commit:
            lancamento.save()
        return lancamento


class RelatorioCompetenciaForm(forms.Form):
    empresa = forms.ModelChoiceField(
        queryset=Empresa.objects.all(), 
        label='Empresa',
        widget=forms.Select(attrs={'autocomplete': 'off'})
    )
    funcionario = forms.ModelChoiceField(
        queryset=Funcionario.objects.none(), 
        label='Funcionário (opcional)', 
        required=False,
        widget=forms.Select(attrs={'autocomplete': 'off'})
    )
    competencia = forms.CharField(
        label='Competência Única', 
        required=False, 
        help_text='MM/YYYY - Deixe vazio para calcular TODAS as competências em aberto',
        widget=forms.TextInput(attrs={'autocomplete': 'off', 'placeholder': 'Vazio = todas em aberto'})
    )
    competencias = forms.CharField(
        label='Múltiplas competências (uma por linha)', 
        required=False, 
        help_text='Uma por linha no formato MM/YYYY. Ignora se competência única estiver preenchida', 
        widget=forms.Textarea(attrs={'rows': 3, 'autocomplete': 'off', 'placeholder': '01/2024\n02/2024\n03/2024'})
    )
    agrupamento = forms.ChoiceField(
        label='Agrupar por',
        choices=[
            ('competencia', 'Competência'),
            ('ano', 'Ano'),
            ('funcionario', 'Funcionário'),
        ],
        initial='competencia',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    data_pagamento = forms.DateField(
        label='Data de Pagamento', 
        required=False, 
        widget=forms.DateInput(attrs={'type': 'date', 'autocomplete': 'off'})
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            allowed_ids = get_allowed_empresa_ids(user)
            if allowed_ids is not None:
                self.fields['empresa'].queryset = Empresa.objects.filter(codigo__in=allowed_ids)
        
        # Se o formulário tem dados (POST), filtra funcionários pela empresa selecionada
        if 'data' in kwargs and kwargs['data'].get('empresa'):
            try:
                empresa_id = int(kwargs['data'].get('empresa'))
                self.fields['funcionario'].queryset = Funcionario.objects.filter(vinculos__empresa_id=empresa_id).distinct()
            except (ValueError, TypeError):
                self.fields['funcionario'].queryset = Funcionario.objects.none()
        elif user is not None and allowed_ids is not None:
            # Se não tem empresa selecionada, mostra todos das empresas permitidas
            self.fields['funcionario'].queryset = Funcionario.objects.filter(vinculos__empresa__codigo__in=allowed_ids).distinct()


class LegacyImportForm(forms.Form):
    """Formulário para importar dados históricos do sistema legado (VB6)"""
    
    IMPORT_TYPE_CHOICES = [
        ('empresas', 'Importar Empresas'),
        ('funcionarios', 'Importar Funcionários'),
        ('lancamentos', 'Importar Lançamentos (Base FGTS)'),
    ]
    
    csv_file = forms.FileField(
        label='Arquivo CSV',
        help_text='Selecione um arquivo CSV com os dados do sistema legado',
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.csv',
            'required': True
        })
    )
    
    import_type = forms.ChoiceField(
        label='Tipo de Importação',
        choices=IMPORT_TYPE_CHOICES,
        widget=forms.RadioSelect(attrs={
            'class': 'form-check-input'
        }),
        initial='lancamentos'
    )
    
    empresa = forms.ModelChoiceField(
        label='Empresa (obrigatório para funcionários/lançamentos)',
        queryset=Empresa.objects.all(),
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-select'
        })
    )
    
    skip_duplicates = forms.BooleanField(
        label='Pular registros duplicados',
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        })
    )
    
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            allowed_ids = get_allowed_empresa_ids(user)
            if allowed_ids is not None:
                self.fields['empresa'].queryset = Empresa.objects.filter(codigo__in=allowed_ids)
    
    def clean(self):
        """Validação customizada do formulário"""
        cleaned_data = super().clean()
        import_type = cleaned_data.get('import_type')
        csv_file = cleaned_data.get('csv_file')
        empresa = cleaned_data.get('empresa')
        
        # Valida tipo de arquivo
        if csv_file:
            if not csv_file.name.lower().endswith('.csv'):
                raise ValidationError('Arquivo deve ser um CSV válido (.csv)')
            
            # Verifica tamanho máximo (20MB)
            if csv_file.size > 20 * 1024 * 1024:
                raise ValidationError('Arquivo não pode ser maior que 20MB')
        
        # Validações específicas por tipo
        if import_type in ['funcionarios', 'lancamentos'] and not empresa:
            raise ValidationError(f'Empresa é obrigatória para importar {import_type}')
        
        return cleaned_data
    
    def clean_csv_file(self):
        """Valida o arquivo CSV"""
        csv_file = self.cleaned_data.get('csv_file')
        if csv_file:
            try:
                # Tenta ler as primeiras linhas para validar formato
                import codecs
                csv_file.seek(0)
                first_line = csv_file.readline().decode('latin1')
                csv_file.seek(0)
                
                if not first_line.strip():
                    raise ValidationError('Arquivo CSV está vazio')
                
            except UnicodeDecodeError:
                raise ValidationError('Arquivo deve estar em formato Latin1 (ISO-8859-1)')
            except Exception as e:
                raise ValidationError(f'Erro ao validar arquivo: {str(e)}')
        
        return csv_file


class ConferenciaLancamentoForm(forms.Form):
    """Formulário para conferência de lançamento"""
    
    valor_conferido = forms.DecimalField(
        label='Valor Conferido',
        required=False,
        max_digits=15,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': '0.01',
            'placeholder': 'Deixe em branco se concordar com o valor calculado'
        }),
        help_text='Informe apenas se o valor estiver diferente do calculado automaticamente'
    )
    
    observacoes = forms.CharField(
        label='Observações',
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Adicione notas sobre esta conferência (opcional)...'
        }),
        help_text='Registre qualquer observação relevante sobre este lançamento'
    )
    
    def __init__(self, *args, conferencia=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.conferencia = conferencia
        
        if conferencia:
            # Pré-preenche com valores existentes
            if conferencia.valor_conferido:
                self.fields['valor_conferido'].initial = conferencia.valor_conferido
            if conferencia.observacoes:
                self.fields['observacoes'].initial = conferencia.observacoes


class RejeicaoLancamentoForm(forms.Form):
    """Formulário para rejeitar um lançamento"""
    
    MOTIVOS_REJEICAO = [
        ('valor_incorreto', 'Valor incorreto'),
        ('competencia_errada', 'Competência errada'),
        ('funcionario_incorreto', 'Funcionário incorreto'),
        ('duplicado', 'Lançamento duplicado'),
        ('data_invalida', 'Data de pagamento inválida'),
        ('falta_documentacao', 'Falta documentação comprobatória'),
        ('outro', 'Outro motivo'),
    ]
    
    motivo_padrao = forms.ChoiceField(
        label='Motivo da Rejeição',
        choices=MOTIVOS_REJEICAO,
        widget=forms.RadioSelect(attrs={
            'class': 'form-check-input'
        }),
        required=True
    )
    
    motivo_detalhado = forms.CharField(
        label='Detalhes',
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Descreva o motivo da rejeição em detalhes...'
        }),
        required=True,
        help_text='Explique claramente o motivo da rejeição para facilitar a correção'
    )
    
    def clean(self):
        cleaned_data = super().clean()
        motivo_padrao = cleaned_data.get('motivo_padrao')
        motivo_detalhado = cleaned_data.get('motivo_detalhado')
        
        if motivo_detalhado and len(motivo_detalhado.strip()) < 10:
            raise ValidationError('Motivo detalhado deve ter pelo menos 10 caracteres')
        
        return cleaned_data


class FiltroConferenciaForm(forms.Form):
    """Formulário para filtrar conferências"""
    
    STATUS_CHOICES = [
        ('TODOS', 'Todos'),
        ('PENDENTE', 'Pendentes'),
        ('CONFERIDO', 'Conferidos'),
        ('PROBLEMA', 'Com Problemas'),
        ('REJEITADO', 'Rejeitados'),
    ]
    
    competencia = forms.CharField(
        label='Competência',
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'MM/YYYY (ex: 01/2025)'
        })
    )
    
    status = forms.ChoiceField(
        label='Status',
        choices=STATUS_CHOICES,
        initial='PENDENTE',
        widget=forms.Select(attrs={
            'class': 'form-select'
        })
    )
    
    funcionario = forms.ModelChoiceField(
        label='Funcionário',
        queryset=Funcionario.objects.none(),
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-select'
        })
    )
    
    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        if empresa:
            self.fields['funcionario'].queryset = Funcionario.objects.filter(empresa=empresa)
