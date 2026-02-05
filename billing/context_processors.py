import logging

from .models import PricingPlan


logger = logging.getLogger(__name__)


def current_pricing(request):
    try:
        plan = PricingPlan.objects.filter(active=True).order_by('sort_order', '-updated_at').first()
    except Exception:
        # Nunca quebrar template (inclui Django Admin) por falha de billing
        logger.exception('Falha ao buscar PricingPlan ativo no context_processor')
        plan = None

    return {'current_plan': plan}
