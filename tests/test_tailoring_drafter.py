import json

from autopilot_jobhunt.tailoring import drafter


class FakeFetchResult:
    def __init__(self, text: str):
        self.text = text


class FakeFetchResponse:
    def __init__(self, text: str):
        self.results = [FakeFetchResult(text)]
        self.errors = []


class FakeTinyFish:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.fetch = self

    def get_contents(self, urls, format='markdown'):
        return FakeFetchResponse('# Job Description')


def test_draft_application_strips_fenced_llm_output(tmp_path, monkeypatch):
    resume_path = tmp_path / 'resume.md'
    resume_path.write_text('# Resume\nExperience', encoding='utf-8')
    last_scan_path = tmp_path / 'last_scan.json'
    last_scan_path.write_text(json.dumps([{
        'url': 'https://example.com/jobs/1',
        'company': 'Example Co',
        'title': 'Engineer',
    }]), encoding='utf-8')

    replies = iter([
        '```markdown\n# Tailored Resume\n- Bullet\n```',
        '```markdown\nDear Hiring Team,\nBody\n```',
        '```text\nApply at https://example.com\n```',
    ])
    pdf_texts = []

    monkeypatch.setattr(drafter, 'TinyFish', FakeTinyFish)
    monkeypatch.setattr(drafter, 'chat_with_llm', lambda *args, **kwargs: next(replies))
    monkeypatch.setattr(drafter, 'write_text_pdf', lambda text, output_path, **kwargs: pdf_texts.append(text) or output_path)

    output_dir = drafter.draft_application(
        {
            'tinyfish_api_key': 'test-key',
            'candidate': {'name': 'Jane Doe', 'resume_path': str(resume_path)},
        },
        '#1',
        last_scan_path=last_scan_path,
        output_dir=tmp_path / 'output',
    )

    resume_md = next(output_dir.glob('resume_*.md')).read_text(encoding='utf-8')
    cover_md = next(output_dir.glob('cover_letter_*.md')).read_text(encoding='utf-8')
    info_txt = (output_dir / 'application_info.txt').read_text(encoding='utf-8')

    assert resume_md == '# Tailored Resume\n- Bullet'
    assert cover_md == 'Dear Hiring Team,\nBody'
    assert '```' not in info_txt
    assert pdf_texts == ['# Tailored Resume\n- Bullet', 'Dear Hiring Team,\nBody']
