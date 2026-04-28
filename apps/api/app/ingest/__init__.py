"""Data ingestion pipelines for Palimpsest NYC.

See `apps/api/app/ingest/README.md` for source catalog, licenses, and the
bronze/silver/gold tier model. Each ingestor implements the `Ingestor`
protocol so the worker service can discover and run them generically.
"""

from app.ingest.base import Ingestor, IngestReport
from app.ingest.scope import SCOPE_BBOX, ScopeBbox

__all__ = ["Ingestor", "IngestReport", "SCOPE_BBOX", "ScopeBbox"]
