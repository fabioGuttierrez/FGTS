
from django import forms
from indices.services.indice_service import IndiceFGTSService
from django.utils import timezone

class FGTSCalculadoraForm(forms.Form):

    def clean_competencia(self):
        competencia = self.cleaned_data['competencia']
        from datetime import datetime
        competencia_dt = None
        try:
            competencia_dt = datetime.strptime(competencia, '%m/%Y').date().replace(day=1)
        except Exception:
            raise forms.ValidationError('Competência inválida. Use o formato MM/AAAA.')
        min_competencia = datetime.strptime('01/2000', '%m/%Y').date().replace(day=1)
        if competencia_dt < min_competencia:
            raise forms.ValidationError('Para consultar competências anteriores a 01/2000, contrate o plano pago e tenha acesso a este e muitos outros recursos avançados.')
        return competencia

    def clean_data_pagamento(self):
        data_pagamento = self.cleaned_data['data_pagamento']
        hoje = timezone.now().date()
        if data_pagamento < hoje:
            raise forms.ValidationError('A data de pagamento não pode ser menor que hoje.')
        data_maxima = IndiceFGTSService.obter_ultima_data_base()
        if data_maxima and data_pagamento > data_maxima:
            raise forms.ValidationError(f'A data de pagamento não pode ser maior que {data_maxima.strftime("%d/%m/%Y")}.')
        # Não permitir sábado ou domingo
        if data_pagamento.weekday() in (5, 6):
            raise forms.ValidationError('A data de pagamento não pode ser sábado ou domingo.')
        return data_pagamento
    base_fgts = forms.DecimalField(
        label="Base FGTS",
        decimal_places=2,
        max_digits=12,
        widget=forms.NumberInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'Ex: 2500,00'
        })
    )
    competencia = forms.CharField(
        label="Competência",
        max_length=7,
        help_text="MM/AAAA",
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'MM/AAAA'
        })
    )
    data_pagamento = forms.DateField(
        label="Data de Pagamento",
        widget=forms.DateInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'dd/mm/aaaa',
            'type': 'date'
        })
    )
