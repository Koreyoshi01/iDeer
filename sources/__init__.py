from sources.github_source import GitHubSource
from sources.huggingface_source import HuggingFaceSource

SOURCE_REGISTRY = {
    "github": GitHubSource,
    "huggingface": HuggingFaceSource,
}
