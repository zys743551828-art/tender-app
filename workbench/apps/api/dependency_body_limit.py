"""Check exact received bytes, including whitespace and escaped JSON, before service calls."""

from fastapi import Request

from packages.domain.package_dependency_limits import require_transport_size


async def require_dependency_request_bytes(request: Request) -> None:
    require_transport_size(len(await request.body()))
