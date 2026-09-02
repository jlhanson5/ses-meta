"""Source registry. Adding a source = add a class here with the same interface."""
from .europepmc import EuropePMC
from .openalex import OpenAlex
from .pubmed import PubMed
from .semanticscholar import SemanticScholar

# name -> class. run.py iterates this so nothing else is hardcoded.
SOURCES = {
    PubMed.name: PubMed,
    EuropePMC.name: EuropePMC,
    OpenAlex.name: OpenAlex,
    SemanticScholar.name: SemanticScholar,
}

__all__ = ["SOURCES", "PubMed", "EuropePMC", "OpenAlex", "SemanticScholar"]
