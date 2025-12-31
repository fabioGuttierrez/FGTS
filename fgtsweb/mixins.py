from typing import Iterable, Optional
from django.db.models import QuerySet


def get_allowed_empresa_ids(user) -> Optional[list]:
    """Return allowed empresa IDs for the user.
    - None means unrestricted (superuser).
    - Empty list means no access.
    """
    if not getattr(user, "is_authenticated", False):
        return []
    if getattr(user, "is_superuser", False):
        return None

    allowed = set()
    if getattr(user, "empresa", None):
        allowed.add(user.empresa.codigo)

    if getattr(user, "is_multi_empresa", False):
        try:
            allowed.update(user.empresas_permitidas.values_list("codigo", flat=True))
        except Exception:
            # If relation not ready yet, ignore
            pass

    return list(allowed)


def is_empresa_allowed(user, empresa_id: int) -> bool:
    allowed = get_allowed_empresa_ids(user)
    if allowed is None:
        return True
    return empresa_id in allowed


class EmpresaScopeMixin:
    """Mixin to scope querysets by empresa for multi-tenant isolation."""

    def get_allowed_empresa_ids(self) -> Optional[list]:
        return get_allowed_empresa_ids(self.request.user)

    def filter_queryset_by_empresa(self, qs: QuerySet) -> QuerySet:
        allowed = self.get_allowed_empresa_ids()
        if allowed is None:
            return qs
        if not allowed:
            return qs.none()
        model_field_names = {f.name for f in qs.model._meta.fields}
        if "empresa_id" in model_field_names:
            return qs.filter(empresa_id__in=allowed)
        elif "empresa" in model_field_names:
            # Usar lookup direto no campo ForeignKey (por codigo da Empresa)
            return qs.filter(empresa__codigo__in=allowed)
        return qs.none()

    def get_queryset(self):
        qs = super().get_queryset()
        return self.filter_queryset_by_empresa(qs)
