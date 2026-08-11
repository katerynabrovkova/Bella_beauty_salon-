from rest_framework.pagination import PageNumberPagination


class DefaultPagination(PageNumberPagination):
    """
    Global default (docs/ARCHITECTURE.md § 13): fixed default page size,
    overridable via ?page_size=, capped so a client can't force an
    unbounded response.
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
