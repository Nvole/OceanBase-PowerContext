def test_rejects_html_in_document_type(client):
    content = b'# Type test\ntype: <img src=x onerror=alert(1)>\n\nBody'
    response = client.post('/api/documents/upload', files={'file': ('type.md', content)})
    assert response.status_code == 400


def test_tag_wildcards_are_literal(client):
    for filename, tag in [('literal.md', 'tag_%'), ('other.md', 'tagXYZ')]:
        content = f'# Tag test\ntype: reading\ntags: {tag}\n\nTAG_LITERAL_CHECK'
        assert client.post('/api/documents/upload', files={'file': (filename, content.encode())}).status_code == 200
    response = client.get('/api/documents/search', params={'keyword': 'TAG_LITERAL_CHECK', 'tag': 'tag_%'})
    assert response.status_code == 200
    assert [document['tags'] for document in response.json()] == ['tag_%']


def test_keyword_wildcards_are_literal(client):
    for filename, body in [('literal.md', 'BODY_%'), ('other.md', 'BODYXYZ')]:
        content = f'# Keyword test\ntype: reading\n\n{body}'
        assert client.post('/api/documents/upload', files={'file': (filename, content.encode())}).status_code == 200
    response = client.get('/api/documents/search', params={'keyword': 'BODY_%'})
    assert response.status_code == 200
    assert len(response.json()) == 1
