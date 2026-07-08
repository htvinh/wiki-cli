"""
plugin.py

Plugin interface ABCs and default implementations for the wiki compiler
pipeline. All plugins inherit from Plugin for lifecycle management.
"""

from abc import ABC, abstractmethod


class Plugin(ABC):
    def initialize(self, config) -> None:
        pass

    def shutdown(self) -> None:
        pass


class Extractor(Plugin):
    @abstractmethod
    def extract(self, path: str):
        ...


class TxtExtractor(Extractor):
    def extract(self, path: str):
        from extractor import extract_entity
        return extract_entity(path)


class Renderer(Plugin):
    @abstractmethod
    def render(self, entity, graph_edges: dict,
               entities: dict, existing_path: str | None = None) -> str:
        ...


class MarkdownRenderer(Renderer):
    def render(self, entity, graph_edges, entities, existing_path=None):
        from rewriter import render_page
        return render_page(entity, graph_edges, entities, existing_path)


class Validator(Plugin):
    @abstractmethod
    def validate(self, output_dir: str):
        ...


class WikiLinter(Validator):
    def validate(self, output_dir: str):
        from linter import lint
        return lint(output_dir)


class LinkResolver(Plugin):
    @abstractmethod
    def resolve(self, link_name: str,
                known_slugs: set[str]) -> str | None:
        ...

    @abstractmethod
    def slugify(self, name: str) -> str:
        ...


class WikiLinkResolver(LinkResolver):
    def resolve(self, link_name: str,
                known_slugs: set[str]) -> str | None:
        slug = self.slugify(link_name)
        return slug if slug in known_slugs else None

    def slugify(self, name: str) -> str:
        return name.lower().replace(" ", "_").replace("-", "_")
