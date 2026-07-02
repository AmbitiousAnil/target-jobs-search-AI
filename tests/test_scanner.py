from job_hunt import scanner


def test_job_matches_country_filter_accepts_city_only_location():
    job = {
        "title": "Backend Engineer",
        "location": "Berlin",
        "content": "Hybrid role in Berlin office.",
    }

    assert scanner.job_matches_country_filter(job, ["Germany"]) is True


def test_job_matches_country_filter_rejects_other_country_city():
    job = {
        "title": "Backend Engineer",
        "location": "Paris",
        "content": "Hybrid role in Paris office.",
    }

    assert scanner.job_matches_country_filter(job, ["Germany"]) is False


def test_job_matches_country_filter_accepts_bengaluru_for_india():
    job = {
        "title": "Platform Engineer",
        "location": "Bengaluru",
        "content": "Hybrid role based in Bengaluru.",
    }

    assert scanner.job_matches_country_filter(job, ["India"]) is True


def test_job_matches_country_filter_accepts_usa_alias_for_new_york():
    job = {
        "title": "Backend Engineer",
        "location": "New York",
        "content": "Hybrid role based in New York.",
    }

    assert scanner.job_matches_country_filter(job, ["USA"]) is True


def test_build_candidate_profile_includes_preferred_locations():
    profile = scanner._build_candidate_profile(
        {
            "candidate": {
                "name": "Candidate",
                "profile": "Senior ML engineer",
                "countries": ["Germany", "USA"],
            }
        }
    )

    assert "Preferred locations: Germany, USA" in profile
