from .models import PricingPlan


def current_pricing(request):
    plan = PricingPlan.objects.filter(active=True).order_by('sort_order', '-updated_at').first()
    return {'current_plan': plan}
