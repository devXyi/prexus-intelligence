from . import epss, firms, gdelt, kev

# connector name → parser(text, fetched_at) -> (records, errors). EPSS is enrichment, handled in ingest.
PARSERS = {"kev": kev.parse, "gdelt": gdelt.parse, "firms": firms.parse}
