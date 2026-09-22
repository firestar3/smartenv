"""Azure Key Vault source (requires the ``smartenv-config[azure]`` extra).

:class:`AzureSource` reads one or more secrets from an Azure Key Vault and
serves them as a flat configuration mapping::

    from smartenv.sources import AzureSource

    source = AzureSource(vault_url="https://myvault.vault.azure.net",
                         secret_names=["db-password", "api-key"])
    values = source.load()          # {"DB-PASSWORD": "...", "API-KEY": "..."}

Secret names are uppercased into keys (dashes are preserved so that
``cast()``-declared schema keys keep matching). When no ``secret_names`` are
given, every secret of the vault is listed and fetched. The module imports
:mod:`azure.keyvault.secrets` and :mod:`azure.identity` lazily, so a plain
``import smartenv.sources`` never pulls them in.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from smartenv.exceptions import CloudAuthError
from smartenv.sources.base import CloudSource

__all__ = ["AzureSource"]


class AzureSource(CloudSource):
    """Source backed by an Azure Key Vault.

    Args:
        vault_url: URL of the vault, e.g.
            ``"https://myvault.vault.azure.net"``. When omitted it is read from
            the ``AZURE_VAULT_URL`` environment variable.
        secret_names: Names of the secrets to fetch. When omitted,
            every secret of the vault is listed and fetched, which requires the
            additional ``get``/``list`` permissions.
        cache: When ``True``, the first successful fetch is cached and reused.
        cache_ttl: Positive finite cache lifetime in seconds, or ``None`` for
            indefinite caching. Expiration is checked when loading.

    Attributes:
        vault_url: Resolved vault URL, or ``""`` when unset.
        secret_names: Names to fetch, or ``None`` for "fetch all".
    """

    def __init__(
        self,
        vault_url: Optional[str] = None,
        secret_names: Optional[List[str]] = None,
        cache: bool = True,
        cache_ttl: Optional[float] = None,
    ) -> None:
        super().__init__(cache=cache, cache_ttl=cache_ttl)
        self.vault_url = vault_url or os.environ.get("AZURE_VAULT_URL", "")
        self.secret_names = list(secret_names) if secret_names is not None else None
        self._client: Any = None

    @property
    def name(self) -> str:
        """Return the identifier of the source.

        Returns:
            Always ``"azure_secrets"``.
        """
        return "azure_secrets"

    def _fetch(self) -> Dict[str, str]:
        """Fetch the secrets from Azure Key Vault.

        Returns:
            A flat mapping of uppercased secret name to its unchanged value.

        Raises:
            CloudAuthError: If the SDK is missing or a vault call fails.
        """
        try:
            from azure.identity import DefaultAzureCredential
            from azure.keyvault.secrets import SecretClient
        except ImportError as exc:
            raise CloudAuthError(
                "azure",
                message=(
                    "the azure_secrets source needs azure-keyvault-secrets and "
                    f"azure-identity, which are unavailable ({exc}); install "
                    "them with: pip install smartenv-config[azure]"
                ),
            ) from exc
        if not self.vault_url.strip():
            raise CloudAuthError(
                "azure", message="provide vault_url or set the AZURE_VAULT_URL environment variable"
            )
        try:
            if self._client is None:
                self._client = SecretClient(
                    vault_url=self.vault_url, credential=DefaultAzureCredential()
                )
            names = (
                self._list_secret_names(self._client)
                if self.secret_names is None
                else self.secret_names
            )
            values: Dict[str, str] = {}
            for secret_name in names:
                if not secret_name.strip():
                    raise ValueError("secret names must be non-empty")
                values.update(self._fetch_one(self._client, secret_name))
            return values
        except CloudAuthError:
            raise
        except Exception as exc:
            raise CloudAuthError("azure", reason=str(exc)) from exc

    def _fetch_one(self, client: Any, secret_name: str) -> Dict[str, str]:
        """Fetch a single secret by name.

        Args:
            client: Key Vault ``SecretClient``.
            secret_name: Name of the secret to read.

        Returns:
            A mapping of uppercased secret name to its unchanged value.

        Raises:
            CloudAuthError: If the API call fails.
        """
        try:
            secret = client.get_secret(secret_name)
        except Exception as exc:
            raise CloudAuthError("azure", reason=str(exc)) from exc
        value = getattr(secret, "value", None)
        return {secret_name.upper(): "" if value is None else str(value)}

    def _list_secret_names(self, client: Any) -> List[str]:
        """List the names of every secret in the vault.

        Args:
            client: Key Vault ``SecretClient``.

        Returns:
            The secret names, in vault order.

        Raises:
            CloudAuthError: If listing fails.
        """
        try:
            properties = client.list_properties_of_secrets()
        except Exception as exc:
            raise CloudAuthError("azure", reason=str(exc)) from exc
        names: List[str] = []
        for item in properties:
            name = getattr(item, "name", None)
            if name:
                names.append(str(name))
        return names
