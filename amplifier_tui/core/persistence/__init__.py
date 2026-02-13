"""Persistence layer – each store owns its file path, data format, and I/O."""

from .aliases import AliasStore
from .bookmarks import BookmarkStore
from .clipboard import ClipboardStore
from .drafts import DraftStore
from .notes import NoteStore
from .pinned_sessions import PinnedSessionStore
from .pins import MessagePinStore
from .refs import RefStore
from .session_names import SessionNameStore
from .snippets import SnippetStore
from .tags import TagStore
from .templates import TemplateStore
from .projector_links import ProjectorLinkStore

__all__ = [
    "AliasStore",
    "BookmarkStore",
    "ClipboardStore",
    "DraftStore",
    "MessagePinStore",
    "NoteStore",
    "PinnedSessionStore",
    "ProjectorLinkStore",
    "RefStore",
    "SessionNameStore",
    "SnippetStore",
    "TagStore",
    "TemplateStore",
]
