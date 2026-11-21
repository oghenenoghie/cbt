from fastapi import APIRouter, Depends

from app.integrations.auth import IntegrationPrincipal, get_integration_principal
from app.integrations.envelope import EnvelopeRoute

router = APIRouter(prefix="/integrations", tags=["integration API"], route_class=EnvelopeRoute)


@router.get("/me")
async def get_current_integration(
    principal: IntegrationPrincipal = Depends(get_integration_principal),
) -> dict[str, object]:
    """Return the authenticated integration's tenant-bound identity and scopes."""
    return {
        "tenant_id": principal.tenant_id,
        "integration_id": principal.integration_id,
        "scopes": sorted(principal.scopes),
    }
