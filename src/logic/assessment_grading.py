"""Pure grading for frozen server-side assessment material."""

def grade_question(question_type, answer, response):
    if question_type == "true_false":
        return isinstance(response, bool) and isinstance(answer, bool) and response == answer
    if question_type in {"single_choice", "short_answer"}:
        if question_type == "short_answer":
            accepted = answer if isinstance(answer, list) else [answer]
            return str(response or "").strip().casefold() in {str(v).strip().casefold() for v in accepted}
        return response == answer
    if question_type == "multiple_choice":
        return set(response or []) == set(answer or [])
    if question_type == "matching":
        return dict(response or {}) == dict(answer or {})
    if question_type == "ordering":
        return list(response or []) == list(answer or [])
    return False


def grade_assessment(rows, responses):
    results = []
    for row in rows:
        key = row.get("grading_key_json") or {}
        response = responses.get(str(row.get("position")))
        correct = grade_question(key.get("type"), key.get("answer"), response)
        results.append({"position": row.get("position"), "question_id": row.get("question_id"), "user_answer": response, "is_correct": correct})
    score = sum(item["is_correct"] for item in results)
    total = len(results)
    return results, score, round(score / total * 100, 1) if total else 0.0
