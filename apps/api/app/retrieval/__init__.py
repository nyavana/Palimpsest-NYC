"""Retrieval module — dense, sparse, hybrid, reranked retrievers.

Selected by RETRIEVAL_MODE (see app.retrieval.factory). The agent loop's
`search_places` tool uses the factory; it never imports a concrete retriever
class directly.
"""
