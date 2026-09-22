"""AWS Secrets Manager source (requires the ``smartenv[aws]`` extra).

:class:`AwsSource` reads a single secret from AWS Secrets Manager and turns it
into a flat configuration mapping::

    from smartenv.sources import AwsSource

    source = AwsSource(secret_name="prod/myapp", region="eu-west-1")
    values = source.load()          # {"PORT": "8080", "HOST": "db.example"}

The secret payload may be a JSON object — flattened with the same rules as the
JSON source — or any plain string, which is served under the ``AWS_SECRET`` key.
The module imports :mod:`boto3` lazily, so a plain ``import smartenv.sources``
never pulls it in.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from smartenv.exceptions import CloudAuthError
from smartenv.sources.base import CloudSource, parse_secret_payload

__all__ = ["AwsSource"]

_DEFAULT_REGION = "us-east-1"


class AwsSource(CloudSource):
    """Source backed by a single AWS Secrets Manager secret.

    Args:
        secret_name: Name (or ARN) of the secret. When omitted it is read from
            the ``AWS_SECRET_NAME`` environment variable.
        region: AWS region of the secret. When omitted it is read from the
            ``AWS_REGION`` environment variable, falling back to
            ``"us-east-1"``.
        cache: When ``True``, the first successful fetch is cached and reused.

    Attributes:
        secret_name: Resolved secret name, or ``""`` when unset.
        region: Resolved region.
    """

    def __init__(
        self,
        secret_name: Optional[str] = None,
        region: Optional[str] = None,
        cache: bool = True,
    ) -> None:
        super().__init__(cache=cache)
        self.secret_name = secret_name or os.environ.get("AWS_SECRET_NAME", "")
        self.region = region or os.environ.get("AWS_REGION", _DEFAULT_REGION)
        self._client: Any = None

    @property
    def name(self) -> str:
        """Return the identifier of the source.

        Returns:
            Always ``"aws_secrets"``.
        """
        return "aws_secrets"

    def _fetch(self) -> Dict[str, str]:
        """Fetch the secret from AWS Secrets Manager.

        Returns:
            A flat mapping of key to string value; a JSON object payload is
            flattened, any other payload is served as ``{"AWS_SECRET": ...}``.

        Raises:
            CloudAuthError: If ``boto3`` is missing or the API call fails.
        """
        try:
            import boto3
        except ImportError as exc:
            raise CloudAuthError(
                "aws",
                message=(
                    "the aws_secrets source needs boto3, which is unavailable "
                    f"({exc}); install it with: pip install smartenv[aws]"
                ),
            ) from exc
        if not self.secret_name:
            raise CloudAuthError(
                "aws", message="provide secret_name or set the AWS_SECRET_NAME environment variable"
            )
        if self._client is None:
            try:
                self._client = boto3.client("secretsmanager", region_name=self.region)
            except Exception as exc:
                raise CloudAuthError("aws", reason=str(exc)) from exc
        try:
            response = self._client.get_secret_value(SecretId=self.secret_name)
        except Exception as exc:  # botocore exposes a deep, versioned hierarchy.
            raise CloudAuthError("aws", reason=str(exc)) from exc
        raw = str(response.get("SecretString") or "")
        return parse_secret_payload(raw, default_key="AWS_SECRET")
