from sources.github_source import GitHubSource
from sources.huggingface_source import HuggingFaceSource
from sources.twitter_source import TwitterSource
from sources.arxiv_source import ArxivSource
from sources.alphaxiv_source import AlphaXivSource
from sources.semanticscholar_source import SemanticScholarSource

SOURCE_REGISTRY = {
    "github": GitHubSource,
    "huggingface": HuggingFaceSource,
    "twitter": TwitterSource,
    "arxiv": ArxivSource,
    "alphaxiv": AlphaXivSource,
    "semanticscholar": SemanticScholarSource,
}
