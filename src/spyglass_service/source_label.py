"""The source label a card shows: the name the user gave its feed in the Feeds tab, else the stored origin.

The stored `Item.origin` is the feed's own title at collection time, which for some feeds is raw text
(an arXiv search feed's title is the whole query). The user's name lives on the Feed row, so the label
is looked up when a card is shown: a rename relabels every card at once and no item is rewritten.
"""

from collections.abc import Mapping

from sqlmodel import Session, select

from spyglass_service.models import Feed, Item


def user_feed_names(session: Session) -> dict[str, str]:
    """Map each feed address to the name the user set for it in the Feeds tab.

    Only names the user set count (`name_overridden`): a name Spyglass filled in itself is often
    the bare site address ("www.youtube.com"), which reads worse than the feed's own title. A
    blank user name is skipped so the card falls back to its stored origin.

    Args:
        session: An open database session.

    Returns:
        {feed_url: user name}; empty when no feed has a user-set name.
    """
    rows = session.exec(
        select(Feed.feed_url, Feed.name).where(Feed.name_overridden == True)  # noqa: E712
    ).all()
    return {url: name.strip() for url, name in rows if name and name.strip()}


def display_origin(item: Item, names: Mapping[str, str]) -> str | None:
    """The label to show for an item's source.

    Args:
        item: The collected item.
        names: The map from `user_feed_names`.

    Returns:
        The user's name for the item's feed when there is one, otherwise the item's stored origin
        (which may be None, e.g. for a bookmark with no publication name).
    """
    if item.feed_url and item.feed_url in names:
        return names[item.feed_url]
    return item.origin
