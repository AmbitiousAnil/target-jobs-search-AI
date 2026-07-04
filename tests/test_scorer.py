from autopilot_jobhunt.scoring import scorer


def test_score_jobs_skips_invalid_json_and_non_numeric_scores(monkeypatch):
    replies = iter([
        '{"score": 92, "title": "Role A", "reason": "strong fit", "worth_applying": true}',
        'Here is the score:\n{"score": 88, "title": "Role B", "reason": "good"',
        '```json\n{"score": "not-a-number", "title": "Role C", "reason": "bad payload"}\n```',
        'Preamble\n{"score": "77", "title": "Role D", "reason": "wrapped reply", "worth_applying": true}\nDone',
    ])

    started = []
    scored = []

    monkeypatch.setattr(scorer, 'build_candidate_profile', lambda config: 'candidate profile')
    monkeypatch.setattr(scorer, 'chat_with_llm', lambda *args, **kwargs: next(replies))

    jobs = [
        {"company": "A", "location": "Remote", "title": "Role A", "url": "https://example.com/a", "content": "desc"},
        {"company": "B", "location": "Remote", "title": "Role B", "url": "https://example.com/b", "content": "desc"},
        {"company": "C", "location": "Remote", "title": "Role C", "url": "https://example.com/c", "content": "desc"},
        {"company": "D", "location": "Remote", "title": "Role D", "url": "https://example.com/d", "content": "desc"},
    ]

    results = scorer.score_jobs(
        jobs,
        'resume text',
        {"candidate": {"min_score": 60}},
        on_job_started=lambda index, job, total: started.append((index, job["url"], total)),
        on_scored_job=lambda job: scored.append(job["url"]),
    )

    assert [job["url"] for job in results] == ["https://example.com/a", "https://example.com/d"]
    assert [job["score"] for job in results] == [92, 77]
    assert started == [
        (1, "https://example.com/a", 4),
        (2, "https://example.com/b", 4),
        (3, "https://example.com/c", 4),
        (4, "https://example.com/d", 4),
    ]
    assert scored == ["https://example.com/a", "https://example.com/d"]
