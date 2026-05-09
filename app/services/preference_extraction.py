import logging
import re
from typing import Any


logger = logging.getLogger(__name__)


TermMap = dict[str, list[str]]


class PreferenceExtractionService:
    GENRE_KEYWORDS: TermMap = {
        "action": ["action"],
        "adventure": ["adventure"],
        "animation": ["animated", "animation", "anime"],
        "comedy": ["comedy", "funny", "humor", "humour", "laugh"],
        "crime": ["crime", "heist", "gangster", "mafia"],
        "documentary": ["documentary", "docu"],
        "drama": ["drama", "dramatic", "character piece"],
        "family": ["family", "kids"],
        "fantasy": ["fantasy", "magic", "fairy tale"],
        "horror": ["horror", "scary"],
        "mystery": ["mystery", "whodunit"],
        "romance": ["romance", "romantic", "love story"],
        "sci-fi": ["sci-fi", "science fiction", "cyberpunk", "space"],
        "thriller": ["thriller", "suspense", "suspenseful"],
        "war": ["war"],
        "western": ["western"],
    }

    SUBGENRE_KEYWORDS: TermMap = {
        "romantic comedy": ["romcom", "rom-com", "rom com", "romantic comedy"],
        "dark comedy": ["dark comedy", "black comedy"],
        "crime thriller": ["crime thriller"],
        "psychological thriller": ["psychological thriller"],
        "legal thriller": ["legal thriller", "courtroom thriller"],
        "political thriller": ["political thriller"],
        "supernatural horror": ["supernatural horror"],
        "slasher": ["slasher"],
        "found footage": ["found footage"],
        "neo-noir": ["neo-noir", "neo noir"],
        "noir": ["noir"],
        "coming-of-age": ["coming of age", "coming-of-age"],
        "road movie": ["road movie", "road trip movie"],
        "buddy comedy": ["buddy comedy"],
        "teen comedy": ["teen comedy"],
        "workplace comedy": ["workplace comedy", "office comedy"],
        "sports drama": ["sports drama"],
        "musical": ["musical"],
        "space opera": ["space opera"],
        "revenge thriller": ["revenge thriller"],
        "period drama": ["period drama", "costume drama"],
    }

    MOOD_KEYWORDS: TermMap = {
        "dark humor": ["dark humor", "dark humour"],
        "lighthearted": ["lighthearted", "light-hearted", "light hearted", "feel good", "feel-good"],
        "comforting": ["comfort", "comforting", "cozy", "cosy", "warm"],
        "fun": ["fun", "upbeat", "playful", "easygoing", "breezy"],
        "funny": ["funny", "hilarious", "make me laugh"],
        "romantic": ["romantic", "swoon", "date night"],
        "emotional": ["emotional", "cry", "heartbreak", "moving"],
        "tense": ["tense", "suspenseful", "nerve-wracking"],
        "dark": ["dark", "moody", "bleak", "grim"],
        "scary": ["scary", "frightening", "creepy"],
        "uplifting": ["uplifting", "inspiring", "hopeful"],
        "melancholic": ["melancholic", "sad", "bittersweet"],
        "thoughtful": ["thoughtful", "reflective", "introspective"],
        "weird": ["weird", "strange", "surreal", "offbeat"],
    }

    TONE_KEYWORDS: TermMap = {
        "playful": ["playful", "goofy"],
        "witty": ["witty", "clever", "sharp dialogue"],
        "sincere": ["sincere", "earnest", "heartfelt"],
        "satirical": ["satire", "satirical"],
        "darkly funny": ["dark humor", "dark humour", "darkly funny"],
        "absurd": ["absurd", "absurdist"],
        "warm": ["warm", "gentle"],
        "gritty": ["gritty", "raw"],
        "bleak": ["bleak", "nihilistic"],
        "stylish": ["stylish", "slick", "visually striking"],
        "cerebral": ["cerebral", "brainy", "intellectual"],
        "grounded": ["grounded", "realistic"],
        "escapist": ["escapist", "escapism"],
        "wholesome": ["wholesome"],
        "edgy": ["edgy", "provocative"],
        "atmospheric": ["atmospheric", "vibey"],
    }

    PACING_KEYWORDS: TermMap = {
        "slow burn": ["slow burn", "slow-burn"],
        "fast-paced": ["fast paced", "fast-paced", "quick paced", "quick-paced"],
        "breezy": ["breezy", "easy watch"],
        "tight": ["tight", "lean"],
        "contemplative": ["contemplative", "meditative"],
        "action-packed": ["action packed", "action-packed"],
    }

    THEME_KEYWORDS: TermMap = {
        "psychological tension": ["psychological", "mind games", "paranoia"],
        "mystery": ["mystery", "secret", "twist", "whodunit"],
        "crime": ["crime", "murder", "detective", "investigation"],
        "friendship": ["friendship", "friends"],
        "family": ["family", "parent", "sibling"],
        "coming of age": ["coming of age", "growing up"],
        "grief": ["grief", "loss", "mourning"],
        "revenge": ["revenge", "vengeance"],
        "identity": ["identity", "self-discovery"],
        "survival": ["survival", "stranded"],
        "ambition": ["ambition", "success", "career"],
        "class": ["class", "rich and poor", "wealth gap"],
        "fame": ["fame", "celebrity"],
        "workplace": ["workplace", "office"],
        "travel": ["travel", "road trip", "vacation"],
        "time travel": ["time travel"],
        "found family": ["found family"],
    }

    LANGUAGE_KEYWORDS: dict[str, str] = {
        "english": "English",
        "hindi": "Hindi",
        "bollywood": "Hindi",
        "korean": "Korean",
        "japanese": "Japanese",
        "spanish": "Spanish",
        "french": "French",
        "german": "German",
        "tamil": "Tamil",
        "telugu": "Telugu",
        "malayalam": "Malayalam",
    }

    POPULARITY_KEYWORDS: TermMap = {
        "underrated": ["underrated", "hidden gem", "lesser known", "under the radar"],
        "popular": ["popular", "mainstream", "crowd pleaser", "crowd-pleaser", "hit"],
        "new": ["new", "recent", "latest", "newer"],
        "classic": ["old", "classic", "retro", "older"],
    }

    VIEWING_CONTEXT_KEYWORDS: TermMap = {
        "alone": ["alone", "solo", "by myself"],
        "group": ["friends", "group", "with people"],
        "date night": ["date night", "date", "partner"],
        "family": ["with family", "family movie"],
        "casual": ["casual", "background", "while eating", "weeknight"],
        "party": ["party", "sleepover"],
    }

    INTENSITY_KEYWORDS: TermMap = {
        "low": ["chill", "low intensity", "not too intense", "easy watch", "relaxed"],
        "medium": ["some tension", "moderately intense", "balanced intensity"],
        "high": ["intense", "very intense", "gripping", "edge of my seat", "disturbing"],
    }

    NEGATION_PATTERNS = [
        r"\bno\s+([a-z0-9][a-z0-9 -]{1,40})",
        r"\bnot\s+([a-z0-9][a-z0-9 -]{1,40})",
        r"\bavoid\s+([a-z0-9][a-z0-9 -]{1,40})",
        r"\bwithout\s+([a-z0-9][a-z0-9 -]{1,40})",
        r"\bdon't want\s+([a-z0-9][a-z0-9 -]{1,40})",
        r"\bdo not want\s+([a-z0-9][a-z0-9 -]{1,40})",
    ]

    CORRECTION_MARKERS = [
        "actually",
        "instead",
        "rather",
        "scratch that",
        "not anymore",
        "change it to",
        "make it",
    ]

    def extract(self, messages: list[str]) -> dict[str, Any]:
        state = self._empty_state()

        for index, message in enumerate(messages):
            self._apply_message(state, message)
            logger.info("Extracted preferences after message %s: %s", index + 1, self._finalize(state))

        return self._finalize(state)
    
    def extract_prioritizing_latest(self, messages: list[str]) -> dict[str, Any]:
        """
        Extract preferences from the full conversation, but dynamically allow the 
        latest request to override stale signals.
        """
        base = self.extract(messages)

        if not messages:
            return base

        latest_message = messages[-1].strip()
        latest_text = latest_message.lower()

        if not latest_text:
            return base

        # Extract what the user asked for *only* in their very last message
        latest = self.extract([latest_message])

        # 1. Determine if the user is ADDING to their request or PIVOTING
        additive_markers = ["also", "and", "add", "plus", "with", "what about", "how about"]
        is_additive = any(marker in latest_text for marker in additive_markers)

        merged = dict(base)

        # 2. If it's a pivot, clear out the stale data
        if not is_additive:
            latest_has_genre = bool(latest.get("genres") or latest.get("subgenres"))
            latest_has_mood = bool(latest.get("moods") or latest.get("tone") or latest.get("themes"))

            if latest_has_genre:
                # User gave a new genre. Wipe old genres AND old moods to start fresh.
                for stale_key in [
                    "genres", "subgenres", "genre", "genre_summary", "avoid_genres",
                    "moods", "mood", "mood_tags", "tone", "themes"
                ]:
                    merged.pop(stale_key, None)
                    
            elif latest_has_mood:
                # User gave a new mood/tone, but no new genre. Keep the genre, swap the vibe.
                for stale_key in ["moods", "mood", "mood_tags", "tone", "themes"]:
                    merged.pop(stale_key, None)

        # 3. Apply the latest signals (either overwriting or combining)
        core_latest_keys = [
            "genres", "subgenres", "moods", "tone", "pacing", "themes",
            "language", "languages", "runtime", "max_runtime_minutes",
            "min_runtime_minutes", "target_runtime_minutes", "era", "year",
            "year_start", "year_end", "popularity_preference",
            "viewing_context", "intensity_level"
        ]

        for key in core_latest_keys:
            if latest.get(key):
                if is_additive and isinstance(merged.get(key), list):
                    # Combine lists uniquely while preserving order
                    merged[key] = list(dict.fromkeys(merged.get(key, []) + latest[key]))
                else:
                    # Overwrite
                    merged[key] = latest[key]

        return self._refresh_derived_preferences(merged)
    
    def _refresh_derived_preferences(self, preferences: dict[str, Any]) -> dict[str, Any]:
        """Recalculates summary fields after merging or overwriting dictionaries."""
        refreshed = dict(preferences)

        if refreshed.get("genres"):
            refreshed["genre_summary"] = " + ".join(refreshed["genres"])
            refreshed["genre"] = refreshed["genre_summary"]
        else:
            refreshed.pop("genre_summary", None)
            refreshed.pop("genre", None)

        if refreshed.get("moods"):
            refreshed["mood"] = refreshed["moods"][-1]
            refreshed["mood_tags"] = refreshed["moods"]
        else:
            refreshed.pop("mood", None)
            refreshed.pop("mood_tags", None)

        if refreshed.get("popularity_preference"):
            refreshed["vibe"] = refreshed["popularity_preference"]
        else:
            refreshed.pop("vibe", None)

        avoid_genres = self._avoid_genres(refreshed)
        if avoid_genres:
            refreshed["avoid_genres"] = avoid_genres
        else:
            refreshed.pop("avoid_genres", None)

        return refreshed

    def assess(self, latest_message: str, preferences: dict[str, Any]) -> dict[str, Any]:
        text = latest_message.lower()
        readiness_keys = [
            "genres",
            "subgenres",
            "moods",
            "tone",
            "pacing",
            "themes",
            "liked_references",
            "runtime",
            "language",
            "era",
            "popularity_preference",
            "viewing_context",
            "intensity_level",
        ]
        has_specific_signal = any(bool(preferences.get(key)) for key in readiness_keys)

        vague_requests = [
            "recommend",
            "suggest",
            "what should i watch",
            "pick a movie",
            "anything",
            "something",
        ]
        has_vague_request = any(phrase in text for phrase in vague_requests)

        contradictions = self._find_contradictions(text, preferences)
        if contradictions:
            return {
                "ready": False,
                "needs_followup": True,
                "followup_type": "clarify_contradiction",
                "question": contradictions[0],
            }

        if has_specific_signal:
            return {
                "ready": True,
                "needs_followup": False,
                "followup_type": None,
                "question": None,
            }

        if has_vague_request or len(text.split()) <= 5:
            return {
                "ready": False,
                "needs_followup": True,
                "followup_type": "gather_preferences",
                "question": "What kind of mood, genre, or movie comparison should I use?",
            }

        return {
            "ready": True,
            "needs_followup": False,
            "followup_type": None,
            "question": None,
        }

    def _empty_state(self) -> dict[str, Any]:
        return {
            "genres": [],
            "subgenres": [],
            "moods": [],
            "tone": [],
            "pacing": [],
            "themes": [],
            "liked_references": [],
            "disliked_references": [],
            "liked_elements": [],
            "disliked_elements": [],
            "exclusions": [],
            "languages": [],
        }

    def _apply_message(self, state: dict[str, Any], raw_message: str) -> None:
        message = raw_message.strip()
        text = message.lower()
        if not text:
            return

        self._extract_reference_signals(state, message)
        self._extract_negations(state, text)
        self._extract_terms(state, text, "genres", self.GENRE_KEYWORDS)
        self._extract_terms(state, text, "subgenres", self.SUBGENRE_KEYWORDS)
        self._extract_terms(state, text, "moods", self.MOOD_KEYWORDS)
        self._extract_terms(state, text, "tone", self.TONE_KEYWORDS)
        self._extract_terms(state, text, "pacing", self.PACING_KEYWORDS)
        self._extract_terms(state, text, "themes", self.THEME_KEYWORDS)
        self._extract_terms(state, text, "popularity_preference", self.POPULARITY_KEYWORDS, scalar=True)
        self._extract_terms(state, text, "viewing_context", self.VIEWING_CONTEXT_KEYWORDS, scalar=True)
        self._extract_terms(state, text, "intensity_level", self.INTENSITY_KEYWORDS, scalar=True)
        self._extract_language(state, text)
        self._extract_runtime(state, text)
        self._extract_era(state, text)
        self._apply_corrections(state, text)
        self._apply_subgenre_expansions(state)
        self._refine_overlapping_signals(state, text)
        self._apply_exclusions_to_collections(state)

    def _extract_terms(
        self,
        state: dict[str, Any],
        text: str,
        key: str,
        term_map: TermMap,
        *,
        scalar: bool = False,
    ) -> None:
        for value, keywords in term_map.items():
            if self._contains_any(text, keywords):
                if scalar:
                    state[key] = value
                else:
                    self._add_unique(state[key], value)

    def _extract_language(self, state: dict[str, Any], text: str) -> None:
        for keyword, language in self.LANGUAGE_KEYWORDS.items():
            if self._contains_phrase(text, keyword):
                self._add_unique(state["languages"], language)
                state["language"] = language

    def _extract_runtime(self, state: dict[str, Any], text: str) -> None:
        if self._contains_any(text, ["under two hours", "under 2 hours", "less than two hours"]):
            state["runtime"] = "under 2 hours"
            state["max_runtime_minutes"] = 120
            return

        if self._contains_any(text, ["short", "quick watch", "not too long"]):
            state["runtime"] = "short"
            state["max_runtime_minutes"] = 110
            return

        if self._contains_any(text, ["long", "epic length"]):
            state["runtime"] = "long"
            state["min_runtime_minutes"] = 140
            return

        match = re.search(r"\b(?:under|less than|below)\s+(\d{2,3})\s*(?:min|mins|minutes)\b", text)
        if match:
            minutes = int(match.group(1))
            state["runtime"] = f"under {minutes} minutes"
            state["max_runtime_minutes"] = minutes
            return

        match = re.search(r"\b(\d(?:\.\d)?)\s*(?:h|hr|hrs|hour|hours)\b", text)
        if match:
            hours = float(match.group(1))
            state["runtime"] = f"around {hours:g} hours"
            state["target_runtime_minutes"] = int(hours * 60)

    def _extract_era(self, state: dict[str, Any], text: str) -> None:
        if self._contains_any(text, ["new", "recent", "latest", "newer"]):
            state["era"] = "recent"
        if self._contains_any(text, ["old", "classic", "retro", "older"]):
            state["era"] = "classic"

        decade_match = re.search(r"\b(19[2-9]0|20[0-2]0)s\b", text)
        if decade_match:
            state["era"] = f"{decade_match.group(1)}s"
            state["year_start"] = int(decade_match.group(1))
            state["year_end"] = int(decade_match.group(1)) + 9
            return

        year_match = re.search(r"\b(19[2-9]\d|20[0-2]\d)\b", text)
        if year_match:
            state["year"] = int(year_match.group(1))

    def _extract_reference_signals(self, state: dict[str, Any], message: str) -> None:
        patterns = [
            ("liked_references", r"\b(?:like|similar to|like something like|in the vein of)\s+([A-Z0-9][^,.!?;]{1,60})"),
            ("liked_references", r"\b(?:i liked|i loved|loved|liked)\s+([A-Z0-9][^,.!?;]{1,60})"),
            ("disliked_references", r"\b(?:i disliked|i hated|hated|disliked)\s+([A-Z0-9][^,.!?;]{1,60})"),
        ]
        for key, pattern in patterns:
            for match in re.finditer(pattern, message):
                title = self._clean_reference(match.group(1))
                if title:
                    self._add_unique(state[key], title)

        liked_reason = re.search(r"\b(?:because|for)\s+(?:the\s+)?([^.!?]{3,80})", message, flags=re.IGNORECASE)
        if liked_reason and state["liked_references"]:
            self._add_unique(state["liked_elements"], self._clean_element(liked_reason.group(1)))

        disliked_reason = re.search(
            r"\b(?:but|except|minus)\s+(?:not\s+)?(?:the\s+)?([^.!?]{3,80})",
            message,
            flags=re.IGNORECASE,
        )
        if disliked_reason:
            self._add_unique(state["disliked_elements"], self._clean_element(disliked_reason.group(1)))

    def _extract_negations(self, state: dict[str, Any], text: str) -> None:
        for pattern in self.NEGATION_PATTERNS:
            for match in re.finditer(pattern, text):
                phrase = self._clean_exclusion(match.group(1))
                if not phrase:
                    continue

                self._add_unique(state["disliked_elements"], phrase)
                self._add_unique(state["exclusions"], phrase)

                for key in ["genres", "subgenres", "moods", "tone", "pacing", "themes"]:
                    self._remove_matching_terms(state[key], phrase)

    def _apply_subgenre_expansions(self, state: dict[str, Any]) -> None:
        subgenres = set(state["subgenres"])
        if "romantic comedy" in subgenres:
            self._add_unique(state["genres"], "romance")
            self._add_unique(state["genres"], "comedy")
            self._add_unique(state["moods"], "lighthearted")
        if "dark comedy" in subgenres:
            self._add_unique(state["genres"], "comedy")
            self._add_unique(state["tone"], "satirical")
            self._add_unique(state["moods"], "dark humor")
        if "psychological thriller" in subgenres:
            self._add_unique(state["genres"], "thriller")
            self._add_unique(state["themes"], "psychological tension")
        if "crime thriller" in subgenres:
            self._add_unique(state["genres"], "crime")
            self._add_unique(state["genres"], "thriller")

        if "neo-noir" in subgenres or "noir" in subgenres:
            self._add_unique(state["genres"], "crime")
            self._add_unique(state["genres"], "thriller")
            self._add_unique(state["moods"], "dark")
            self._add_unique(state["tone"], "stylish")

    def _refine_overlapping_signals(self, state: dict[str, Any], text: str) -> None:
        if "dark humor" in state["moods"] and "dark" in state["moods"]:
            explicit_dark_tone = self._contains_any(
                text,
                ["dark tone", "dark mood", "dark atmosphere", "dark drama", "dark thriller", "moody", "bleak", "grim"],
            )
            if not explicit_dark_tone:
                state["moods"].remove("dark")

    def _apply_corrections(self, state: dict[str, Any], text: str) -> None:
        if not any(marker in text for marker in self.CORRECTION_MARKERS):
            return

        current_moods = set(self._matched_values(text, self.MOOD_KEYWORDS))
        current_genres = set(self._matched_values(text, self.GENRE_KEYWORDS))
        current_subgenres = set(self._matched_values(text, self.SUBGENRE_KEYWORDS))
        current_tone = set(self._matched_values(text, self.TONE_KEYWORDS))
        current_themes = set(self._matched_values(text, self.THEME_KEYWORDS))
        current_languages = [
            language
            for keyword, language in self.LANGUAGE_KEYWORDS.items()
            if self._contains_phrase(text, keyword)
        ]
        direction_change = self._is_direction_change(text)

        if direction_change:
            if current_subgenres:
                state["subgenres"] = list(dict.fromkeys(current_subgenres))
                if not current_genres:
                    state["genres"] = []
            if current_genres:
                state["genres"] = list(dict.fromkeys(current_genres))
            if current_moods:
                state["moods"] = list(dict.fromkeys(current_moods))
            if current_tone:
                state["tone"] = list(dict.fromkeys(current_tone))
            current_pacing_values = set(self._matched_values(text, self.PACING_KEYWORDS))
            if current_pacing_values:
                state["pacing"] = list(dict.fromkeys(current_pacing_values))
            if current_themes:
                state["themes"] = list(dict.fromkeys(current_themes))
            if current_languages:
                state["languages"] = list(dict.fromkeys(current_languages))
                state["language"] = current_languages[-1]

        if current_moods.intersection({"lighthearted", "comforting", "fun", "funny", "uplifting"}):
            self._remove_values(state["moods"], ["dark", "scary", "melancholic"])
        if current_moods.intersection({"dark", "scary"}):
            self._remove_values(state["moods"], ["lighthearted", "comforting", "fun", "funny", "uplifting"])

        current_pacing = set(self._matched_values(text, self.PACING_KEYWORDS))
        if current_pacing.intersection({"slow burn", "contemplative"}):
            self._remove_values(state["pacing"], ["fast-paced", "action-packed"])
        if current_pacing.intersection({"fast-paced", "action-packed"}):
            self._remove_values(state["pacing"], ["slow burn", "contemplative"])

        current_popularity = set(self._matched_values(text, self.POPULARITY_KEYWORDS))
        if current_popularity.intersection({"new"}):
            state["popularity_preference"] = "new"
            if state.get("era") == "classic":
                state.pop("era", None)
        if current_popularity.intersection({"classic"}):
            state["popularity_preference"] = "classic"
            if state.get("era") == "recent":
                state.pop("era", None)

        correction_match = re.search(r"\b(?:not|no|avoid|without)\s+([a-z0-9][a-z0-9 -]{1,40})", text)
        if not correction_match:
            return

        phrase = self._clean_exclusion(correction_match.group(1))
        if not phrase:
            return

        for key in ["genres", "subgenres", "moods", "tone", "pacing", "themes"]:
            self._remove_matching_terms(state[key], phrase)
        self._add_unique(state["exclusions"], phrase)

    def _is_direction_change(self, text: str) -> bool:
        strong_markers = [
            "instead",
            "rather",
            "scratch that",
            "not anymore",
            "change it to",
            "make it",
            "actually make",
            "actually do",
            "actually let's",
            "actually lets",
        ]
        return any(marker in text for marker in strong_markers)

    def _apply_exclusions_to_collections(self, state: dict[str, Any]) -> None:
        for phrase in state["exclusions"]:
            for key in ["genres", "subgenres", "moods", "tone", "pacing", "themes"]:
                self._remove_matching_terms(state[key], phrase)

    def _finalize(self, state: dict[str, Any]) -> dict[str, Any]:
        preferences: dict[str, Any] = {}

        for key in [
            "genres",
            "subgenres",
            "moods",
            "tone",
            "pacing",
            "themes",
            "liked_references",
            "disliked_references",
            "liked_elements",
            "disliked_elements",
            "exclusions",
            "languages",
        ]:
            values = state.get(key)
            if values:
                preferences[key] = values

        for key in [
            "runtime",
            "max_runtime_minutes",
            "min_runtime_minutes",
            "target_runtime_minutes",
            "language",
            "era",
            "year",
            "year_start",
            "year_end",
            "popularity_preference",
            "viewing_context",
            "intensity_level",
        ]:
            value = state.get(key)
            if value is not None:
                preferences[key] = value

        if preferences.get("genres"):
            preferences["genre_summary"] = " + ".join(preferences["genres"])
            preferences["genre"] = preferences["genre_summary"]

        if preferences.get("moods"):
            preferences["mood"] = preferences["moods"][-1]
            preferences["mood_tags"] = preferences["moods"]

        if preferences.get("popularity_preference"):
            preferences["vibe"] = preferences["popularity_preference"]

        avoid_genres = self._avoid_genres(preferences)
        if avoid_genres:
            preferences["avoid_genres"] = avoid_genres

        return preferences

    def _avoid_genres(self, preferences: dict[str, Any]) -> list[str]:
        moods = set(preferences.get("moods", []))
        genres = set(preferences.get("genres", []))
        themes = set(preferences.get("themes", []))
        exclusions = set(preferences.get("exclusions", []))
        avoided: list[str] = []

        if moods.intersection({"lighthearted", "comforting", "fun"}) and not themes.intersection(
            {"crime", "mystery", "psychological tension"}
        ):
            avoided.extend(["horror", "thriller", "crime", "mystery"])

        for excluded in exclusions:
            for genre in self.GENRE_KEYWORDS:
                if genre in excluded:
                    avoided.append(genre)

        return [genre for genre in dict.fromkeys(avoided) if genre not in genres and genre not in themes]

    def _find_contradictions(self, text: str, preferences: dict[str, Any]) -> list[str]:
        moods = set(preferences.get("moods", []))
        genres = set(preferences.get("genres", []))
        exclusions = set(preferences.get("exclusions", []))
        questions: list[str] = []

        if moods.intersection({"lighthearted", "comforting", "fun"}) and moods.intersection({"dark", "scary"}):
            questions.append("Should this lean more light and easy, or darker and more intense?")

        if preferences.get("intensity_level") == "low" and any(word in text for word in ["very intense", "disturbing"]):
            questions.append("Do you want a relaxed watch, or are you open to something more intense?")

        if "horror" in genres and any("horror" in item for item in exclusions):
            questions.append("Should I avoid horror entirely, or are you open to something lightly spooky?")

        if "superhero" in text and any("superhero" in item for item in exclusions):
            questions.append("Do you want superhero movies included or avoided?")

        return questions

    def _contains_any(self, text: str, phrases: list[str]) -> bool:
        return any(self._contains_phrase(text, phrase) for phrase in phrases)

    def _matched_values(self, text: str, term_map: TermMap) -> list[str]:
        return [
            value
            for value, keywords in term_map.items()
            if self._contains_any(text, keywords)
        ]

    def _contains_phrase(self, text: str, phrase: str) -> bool:
        escaped = re.escape(phrase.lower()).replace(r"\ ", r"[\s-]+")
        return bool(re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", text))

    def _add_unique(self, items: list[str], value: str) -> None:
        cleaned = value.strip()
        if cleaned and cleaned not in items:
            items.append(cleaned)

    def _remove_matching_terms(self, items: list[str], phrase: str) -> None:
        phrase = phrase.lower()
        items[:] = [
            item
            for item in items
            if item.lower() not in phrase and phrase not in item.lower()
        ]

    def _remove_values(self, items: list[str], values: list[str]) -> None:
        value_set = set(values)
        items[:] = [item for item in items if item not in value_set]

    def _clean_reference(self, value: str) -> str:
        cleaned = re.sub(r"\b(?:but|with|without|because|for|and)\b.*$", "", value, flags=re.IGNORECASE)
        return cleaned.strip(" ,;:-")

    def _clean_element(self, value: str) -> str:
        cleaned = re.sub(r"\b(?:but|except|minus|without|not)\b.*$", "", value, flags=re.IGNORECASE)
        cleaned = re.sub(r"^(?:the|a|an)\s+", "", cleaned.strip(" ,;:-"), flags=re.IGNORECASE)
        return cleaned.strip(" ,;:-")

    def _clean_exclusion(self, value: str) -> str:
        cleaned = re.sub(r"\b(?:but|and|or|please|movie|movies|films?)\b.*$", "", value, flags=re.IGNORECASE)
        cleaned = re.sub(r"^(?:the|a|an|too)\s+", "", cleaned.strip(" ,;:-"), flags=re.IGNORECASE)
        return cleaned.strip(" ,;:-")
