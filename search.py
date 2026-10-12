import re
from html.parser import HTMLParser

import markdown
from sqlalchemy import text

import models
from extensions import db


SEARCH_INDEX_NAME = "page_search"
SEARCH_QUERY_LIMIT = 200
SEARCH_RESULT_LIMIT = 25
WIKI_LINK_PATTERN = re.compile(r"\[\[\s*([^\[\]\n]+?)\s*\]\]")
SEARCH_TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)


class PlainTextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.ignored_tag = None

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.ignored_tag = tag

    def handle_endtag(self, tag):
        if tag == self.ignored_tag:
            self.ignored_tag = None

    def handle_data(self, data):
        if self.ignored_tag is None:
            self.parts.append(data)

    def get_text(self):
        return " ".join(self.parts)


def initialize_search_index():
    require_sqlite()
    index_exists = db.session.execute(
        text(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = :index_name"
        ),
        {"index_name": SEARCH_INDEX_NAME},
    ).scalar()
    db.session.execute(
        text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS page_search USING fts5("
            "page_id UNINDEXED, "
            "title, "
            "body, "
            "tokenize = 'unicode61 remove_diacritics 2'"
            ")"
        )
    )

    if index_exists is None:
        rebuild_search_index()

    db.session.commit()


def rebuild_search_index():
    require_sqlite()
    db.session.execute(text("DELETE FROM page_search"))
    page_rows = (
        db.session.query(models.Pages, models.PageRevisions)
        .join(
            models.PageRevisions,
            models.Pages.current_revision_id == models.PageRevisions.id,
        )
        .all()
    )
    for page, revision in page_rows:
        refresh_page_search(page, revision)

    return len(page_rows)


def refresh_page_search(page, revision=None):
    if revision is None:
        revision = db.session.get(models.PageRevisions, page.current_revision_id)

    delete_page_search(page.id)
    if revision is None:
        return

    db.session.execute(
        text(
            "INSERT INTO page_search (page_id, title, body) "
            "VALUES (:page_id, :title, :body)"
        ),
        {
            "page_id": page.id,
            "title": page.title,
            "body": markdown_to_plain_text(revision.body_markdown),
        },
    )


def delete_page_search(page_id):
    db.session.execute(
        text("DELETE FROM page_search WHERE page_id = :page_id"),
        {"page_id": page_id},
    )


def search_pages(query):
    normalized_query = normalize_text(query)[:SEARCH_QUERY_LIMIT]
    tokens = get_search_tokens(normalized_query)
    if not tokens:
        return []

    match_query = " AND ".join(f'"{token}"' for token in tokens)
    search_rows = db.session.execute(
        text(
            "SELECT CAST(page_id AS INTEGER) AS page_id, title, body, "
            "bm25(page_search, 0.0, 20.0, 1.0) AS relevance "
            "FROM page_search WHERE page_search MATCH :match_query"
        ),
        {"match_query": match_query},
    ).mappings().all()

    page_ids = [row["page_id"] for row in search_rows]
    if not page_ids:
        return []

    pages_by_id = {
        page.id: page
        for page in models.Pages.query.filter(models.Pages.id.in_(page_ids)).all()
    }
    results = []
    for row in search_rows:
        page = pages_by_id.get(row["page_id"])
        if page is None:
            continue

        title_tier = get_title_match_tier(row["title"], normalized_query, tokens)
        title_match = title_tier is not None
        tier = title_tier
        if tier is None:
            tier = 4 if normalized_query in normalize_text(row["body"]) else 5

        results.append(
            {
                "page": page,
                "title_match": title_match,
                "snippet": build_snippet(
                    row["body"],
                    normalized_query,
                    tokens,
                    title_match,
                ),
                "tier": tier,
                "relevance": row["relevance"],
            }
        )

    return sorted(
        results,
        key=lambda result: (
            result["tier"],
            result["relevance"],
            result["page"].title.casefold(),
        ),
    )


def markdown_to_plain_text(body_markdown):
    visible_markdown = WIKI_LINK_PATTERN.sub(
        lambda match: match.group(1).strip(),
        body_markdown,
    )
    parser = PlainTextParser()
    parser.feed(markdown.markdown(visible_markdown))
    parser.close()
    return normalize_whitespace(parser.get_text())


def get_title_match_tier(title, normalized_query, tokens):
    normalized_title = normalize_text(title)
    if normalized_title == normalized_query:
        return 0
    if normalized_title.startswith(normalized_query):
        return 1
    if normalized_query in normalized_title:
        return 2

    title_tokens = set(get_search_tokens(normalized_title))
    if all(token in title_tokens for token in tokens):
        return 3

    return None


def build_snippet(body, normalized_query, tokens, title_match):
    if not body:
        return [{"text": "No content.", "highlight": False}]

    if title_match:
        return [{"text": truncate_text(body, 220), "highlight": False}]

    match_span = find_best_match(body, normalized_query, tokens)
    if match_span is None:
        return [{"text": truncate_text(body, 220), "highlight": False}]

    match_start, match_end = match_span
    start = get_context_start(body, match_start, 80)
    end = get_context_end(body, match_end, 140)
    before = body[start:match_start]
    after = body[match_end:end]
    if start > 0:
        before = f"…{before}"
    if end < len(body):
        after = f"{after}…"

    return [
        {"text": before, "highlight": False},
        {"text": body[match_start:match_end], "highlight": True},
        {"text": after, "highlight": False},
    ]


def find_best_match(body, normalized_query, tokens):
    """Return the strongest query span rather than the earliest token."""
    phrase_pattern = r"\s+".join(
        re.escape(part) for part in normalized_query.split()
    )
    phrase_matches = list(
        re.finditer(
            rf"(?<!\w){phrase_pattern}(?!\w)",
            body,
            re.IGNORECASE,
        )
    )
    token_occurrences = get_token_occurrences(body, tokens)
    if phrase_matches:
        best_phrase = max(
            phrase_matches,
            key=lambda match: (
                count_nearby_tokens(
                    token_occurrences,
                    match.start(),
                    match.end(),
                ),
                -match.start(),
            ),
        )
        return best_phrase.start(), best_phrase.end()

    if not token_occurrences:
        return None

    required_tokens = set(tokens)
    token_counts = {}
    left_index = 0
    best_window = None
    for right_index, (_, _, token) in enumerate(token_occurrences):
        token_counts[token] = token_counts.get(token, 0) + 1
        while len(token_counts) == len(required_tokens):
            window_start = token_occurrences[left_index][0]
            window_end = token_occurrences[right_index][1]
            candidate = (window_end - window_start, window_start, window_end)
            if best_window is None or candidate < best_window:
                best_window = candidate

            left_token = token_occurrences[left_index][2]
            token_counts[left_token] -= 1
            if token_counts[left_token] == 0:
                del token_counts[left_token]
            left_index += 1

    if best_window is not None and best_window[0] <= 160:
        return best_window[1], best_window[2]

    best_occurrence = max(
        token_occurrences,
        key=lambda occurrence: (
            count_nearby_tokens(
                token_occurrences,
                occurrence[0],
                occurrence[1],
            ),
            -occurrence[0],
        ),
    )
    return best_occurrence[0], best_occurrence[1]


def get_token_occurrences(body, tokens):
    occurrences = []
    for token in tokens:
        for match in re.finditer(
            rf"(?<!\w){re.escape(token)}(?!\w)",
            body,
            re.IGNORECASE,
        ):
            occurrences.append((match.start(), match.end(), token))
    return sorted(occurrences, key=lambda occurrence: (occurrence[0], occurrence[1]))


def count_nearby_tokens(occurrences, match_start, match_end):
    context_start = max(0, match_start - 100)
    context_end = match_end + 100
    return sum(
        1
        for occurrence_start, occurrence_end, _ in occurrences
        if occurrence_start >= context_start and occurrence_end <= context_end
    )


def get_context_start(text_value, match_start, context_length):
    start = max(0, match_start - context_length)
    if start == 0:
        return start

    next_space = text_value.find(" ", start)
    if next_space != -1 and next_space < match_start:
        return next_space + 1
    return start


def get_context_end(text_value, match_end, context_length):
    end = min(len(text_value), match_end + context_length)
    if end == len(text_value):
        return end

    previous_space = text_value.rfind(" ", match_end, end)
    if previous_space > match_end:
        return previous_space
    return end


def truncate_text(text_value, limit):
    if len(text_value) <= limit:
        return text_value

    truncated = text_value[:limit]
    final_space = truncated.rfind(" ")
    if final_space > 0:
        truncated = truncated[:final_space]
    return f"{truncated}…"


def normalize_text(text_value):
    return normalize_whitespace(text_value).casefold()


def normalize_whitespace(text_value):
    return " ".join((text_value or "").split())


def get_search_tokens(query):
    return list(dict.fromkeys(SEARCH_TOKEN_PATTERN.findall(query)))


def require_sqlite():
    if db.engine.dialect.name != "sqlite":
        raise RuntimeError("Wiki search currently requires SQLite with FTS5 support.")
