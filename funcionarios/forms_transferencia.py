from django import forms
from empresas.models_grupo import FuncionarioVinculo
from empresas.models import Empresa

class TransferenciaFuncionarioForm(forms.Form):
    empresa_destino = forms.ModelChoiceField(queryset=Empresa.objects.none(), label="Empresa de Destino", widget=forms.Select(attrs={'class': 'form-select'}))
    data_transferencia = forms.DateField(label="Data da Transferência", widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}))
    cargo = forms.CharField(label="Cargo na nova empresa", required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    salario = forms.DecimalField(label="Salário na nova empresa", required=False, max_digits=12, decimal_places=2, widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}))
    observacoes = forms.CharField(label="Observações", required=False, widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}))

    def __init__(self, funcionario, *args, **kwargs):
        super().__init__(*args, **kwargs)
        grupo = funcionario.empresa.grupo if funcionario.empresa else None
        if grupo:
            self.fields['empresa_destino'].queryset = grupo.empresas.exclude(pk=funcionario.empresa.pk)
        else:
            self.fields['empresa_destino'].queryset = Empresa.objects.none()
