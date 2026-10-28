"""A human reading budget includes questions and feedback, not only prose."""

import re


def reading_budget(minutes=5):
    if isinstance(minutes, bool) or not isinstance(minutes, int) or not 2 <= minutes <= 15:
        raise ValueError("Choose a reading budget of 2–15 minutes")
    questions = 2 if minutes <= 3 else 4 if minutes <= 6 else 6
    return {
        "minutes": minutes,
        "max_questions": questions,
        "max_modules": 1 if minutes <= 3 else 2 if minutes <= 6 else 3,
        "max_words": minutes * 160 - questions * 50,
    }


def reading_stats(modules):
    words, questions = 0, 0
    for m in modules:
        text = [m["title"], m["summary"], m["why"], *m["flow"], m["key_code"], *m["pitfalls"]]
        for q in m["questions"]:
            questions += 1
            text += [q["question"], q["explanation"], *(o["text"] for o in q["options"])]
        for f in m.get("findings", []):
            text += [f["title"], f["scenario"], f["evidence"], f["impact"]]
        words += len(re.findall(r"\S+", " ".join(text)))
    return {"words": words, "questions": questions, "minutes": max(1, round(words / 180 + questions / 3))}


def validate_budget(modules, budget):
    stats = reading_stats(modules)
    if (
        len(modules) > budget["max_modules"]
        or stats["questions"] > budget["max_questions"]
        or stats["words"] > budget["max_words"]
    ):
        raise ValueError(
            f"Round exceeds its reading budget: {stats}. Limits: {budget}. Cut tangents, modules or questions; keep the single most useful flow."
        )
    return stats
